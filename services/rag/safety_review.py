"""Safety review of one newly recorded medication against the user's other recent records.

No model is involved: an alert is raised only when label text in the snapshot supports it, and every alert carries
the passage it came from. Two kinds of findings:

    duplicate_ingredient  the two products share an active ingredient and were taken within 24 hours
    label_warning         one product's label (do not use / ask a doctor or pharmacist / drug interactions /
                          warnings) names the other product's ingredient or its drug class

What this cannot do, by design: judge a pair that neither label mentions, or recognise a name outside the alias
table and the snapshot. Those names are returned as `unresolved` so the user is never told "checked" when nothing
was checked. "No alert" is therefore never a statement that the combination is safe.
"""

from __future__ import annotations

import re
import time
from functools import lru_cache
from dataclasses import dataclass, field

from agent import INTERACTION_SECTIONS, plain
from label_retrieval import source_url
from medtrack_server import ApiError, names, values

HOUR_MS = 3_600_000
INTERACTION_WINDOW_MS = 7 * 24 * HOUR_MS  # a record older than this is history, not a current medication
DUPLICATE_WINDOW_MS = 24 * HOUR_MS        # same ingredient twice within a day can exceed the daily maximum
HIGH_SECTIONS = {"do_not_use", "boxed_warning"}
EXCERPT_CHARS = 280
MAX_FINDINGS = 3
NOTE = "只根据说明书原文判断：没有提醒不代表可以一起用，有疑问请咨询医生或药师。"

SECTION_ZH = {
    "do_not_use": "禁用", "boxed_warning": "黑框警告", "ask_doctor_or_pharmacist": "用药前咨询医生或药师",
    "drug_interactions": "药物相互作用", "warnings_and_cautions": "警告与注意事项", "when_using": "使用期间",
    "ask_doctor": "用药前咨询医生", "warnings": "警告", "active_ingredient": "有效成分",
}

# Drug classes as labels phrase them. Matching is on whole words (see `plain`), so "steroid" never hits "nonsteroidal".
CLASSES: dict[str, tuple[str, list[str]]] = {
    "nsaid": ("非甾体抗炎药", ["nsaid", "nsaids", "nonsteroidal anti inflammatory"]),
    "anticoagulant": ("抗凝药", ["anticoagulant", "anticoagulants", "blood thinning", "blood thinner",
                                "blood thinners"]),
    "antiplatelet": ("抗血小板药", ["antiplatelet", "antiplatelet agents"]),
    "steroid": ("糖皮质激素", ["steroid drug", "corticosteroid", "corticosteroids"]),
    "ssri": ("抗抑郁药（SSRI）", ["ssri", "ssris", "selective serotonin reuptake inhibitors", "antidepressant",
                                 "antidepressants"]),
    "maoi": ("单胺氧化酶抑制剂", ["maoi", "maois", "monoamine oxidase inhibitor"]),
    "sedative": ("镇静催眠药", ["sedative", "sedatives", "tranquilizer", "tranquilizers"]),
    "antihistamine": ("抗组胺药", ["antihistamine", "antihistamines"]),
    "ppi": ("质子泵抑制剂", ["proton pump inhibitor", "proton pump inhibitors"]),
    "decongestant": ("减充血剂", ["decongestant", "nasal decongestant"]),
    "diuretic": ("利尿剂", ["diuretic", "diuretics"]),
}

# English ingredient → (Chinese names and common Chinese brands, other English names, classes).
# Fluticasone is deliberately not a "steroid": the labels' "steroid drug" means systemic steroids, not a nasal spray.
INGREDIENTS: dict[str, tuple[list[str], list[str], list[str]]] = {
    "ibuprofen": (["布洛芬", "芬必得", "美林"], [], ["nsaid"]),
    "naproxen": (["萘普生"], [], ["nsaid"]),
    "aspirin": (["阿司匹林", "拜阿司匹灵", "乙酰水杨酸"], ["acetylsalicylic acid"], ["nsaid", "antiplatelet"]),
    "diclofenac": (["双氯芬酸", "扶他林"], [], ["nsaid"]),
    "acetaminophen": (["对乙酰氨基酚", "扑热息痛", "泰诺林", "泰诺", "必理通"], ["paracetamol"], []),
    "diphenhydramine": (["苯海拉明"], [], ["antihistamine"]),
    "chlorpheniramine": (["氯苯那敏", "扑尔敏"], [], ["antihistamine"]),
    "cetirizine": (["西替利嗪", "仙特明"], [], ["antihistamine"]),
    "loratadine": (["氯雷他定", "开瑞坦"], [], ["antihistamine"]),
    "famotidine": (["法莫替丁"], [], []),
    "omeprazole": (["奥美拉唑", "洛赛克"], [], ["ppi"]),
    "esomeprazole": (["埃索美拉唑", "耐信"], [], ["ppi"]),
    "levothyroxine": (["左甲状腺素", "优甲乐", "雷替斯"], [], []),
    "calcium carbonate": (["碳酸钙", "钙尔奇"], [], []),
    "atorvastatin": (["阿托伐他汀", "立普妥"], [], []),
    "sertraline": (["舍曲林", "左洛复"], [], ["ssri"]),
    "fluoxetine": (["氟西汀", "百忧解"], [], ["ssri"]),
    "warfarin": (["华法林"], [], ["anticoagulant"]),
    "rivaroxaban": (["利伐沙班", "拜瑞妥"], [], ["anticoagulant"]),
    "clopidogrel": (["氯吡格雷", "波立维"], [], ["antiplatelet"]),
    "prednisone": (["泼尼松", "强的松"], [], ["steroid"]),
    "dexamethasone": (["地塞米松"], [], ["steroid"]),
    "pseudoephedrine": (["伪麻黄碱"], [], ["decongestant"]),
    "phenylephrine": (["去氧肾上腺素"], [], ["decongestant"]),
    "epinephrine": (["肾上腺素"], ["adrenaline"], []),
    "fluticasone": (["氟替卡松"], [], []),
    "hydrochlorothiazide": (["氢氯噻嗪"], [], ["diuretic"]),
    "furosemide": (["呋塞米", "速尿"], [], ["diuretic"]),
}
SALTS = {"hydrochloride", "hcl", "sodium", "magnesium", "maleate", "trihydrate", "furoate", "propionate",
         "unspecified", "form", "natural", "and", "zinc", "acetate"}
CHILD = re.compile(r"child|junior|infant|jr\b", re.I)
_ZH_ALIASES = sorted(((alias, key) for key, (zh, _, _) in INGREDIENTS.items() for alias in zh), key=lambda a: -len(a[0]))
_EN_ALIASES = sorted(((plain(alias), key) for key, (_, en, _) in INGREDIENTS.items() for alias in [key, *en]),
                     key=lambda a: -len(a[0]))


def canonical(substance: str) -> str:
    """'ATORVASTATIN CALCIUM TRIHYDRATE' → 'atorvastatin'; unknown substances lose their salt words."""
    text = plain(substance)
    for alias, key in _EN_ALIASES:
        if alias in text:
            return key
    return " ".join(w for w in text.split() if w not in SALTS) or text.strip()


NEGATED = re.compile(r"\bno (?:clinically )?(?:significant|meaningful)\b|\bhad no\b|\bdid not\b|\bnot (?:been )?"
                     r"(?:shown|observed|affected)\b")


@lru_cache(maxsize=None)
def _pattern(phrase: str) -> re.Pattern:
    words = [re.escape(w) for w in re.split(r"[\W_]+", phrase) if w]
    return re.compile(r"(?<![A-Za-z0-9])" + r"[\W_]+".join(words) + r"(?![A-Za-z0-9])", re.I)


def same_name(name: str) -> str:
    """Name key for "is this the same product again?". Unlike `plain`, it keeps Chinese characters."""
    return " ".join(re.sub(r"[\W_]+", " ", name.casefold()).split())


def ingredient_zh(key: str) -> str:
    return INGREDIENTS[key][0][0] if key in INGREDIENTS else key


@dataclass
class Med:
    name: str
    ingredients: frozenset[str] = frozenset()
    label: dict | None = None  # the label scanned for this medication: {"id", "version", "name"}
    last_taken_at: int | None = None
    problem: str | None = None  # why it could not be resolved

    def view(self) -> dict:
        return {"name": self.name, "ingredients": sorted(self.ingredients),
                "label": self.label["name"] if self.label else None}


@dataclass
class Finding:
    rank: tuple
    summary: str
    citation: dict
    high: bool
    kind: str


@dataclass
class Review:
    alerts: list = field(default_factory=list)


class SafetyChecker:
    def __init__(self, index) -> None:
        self.index = index
        self.snapshot = index.snapshot
        self._ingredients = {key: frozenset(canonical(s) for s in self._substances(record))
                             for key, record in self.snapshot.records.items()}

    @staticmethod
    def _substances(record) -> list[str]:
        meta = record.get("openfda") or {}
        found = values(meta, "substance_name")
        if not found:  # some labels only list the generic name, e.g. "DIPHENHYDRAMINE HYDROCHLORIDE AND ZINC ACETATE"
            for generic in values(meta, "generic_name"):
                found += [p for p in re.split(r",| and ", generic, flags=re.I) if p.strip()]
        return found

    # ----- resolving names -----------------------------------------------------------------------------------
    def resolve(self, name: str, last_taken_at: int | None = None) -> Med:
        """Chinese names go through the alias table; a product name the snapshot knows wins over English ingredient
        words inside it ("Advil Dual Action with Acetaminophen" is ibuprofen + acetaminophen, not acetaminophen)."""
        med = Med(name.strip(), last_taken_at=last_taken_at)
        found, rest = set(), med.name
        for alias, key in _ZH_ALIASES:
            if alias in rest:
                found.add(key)
                rest = rest.replace(alias, " ")
        if not found:
            problem = self._from_snapshot(med)
            if problem is None:
                return med
        text = plain(rest)
        for alias, key in _EN_ALIASES:
            if alias in text:
                found.add(key)
                text = text.replace(alias, " ")
        if not found:
            med.problem = problem
            return med
        med.ingredients = frozenset(found)
        med.label = self._representative([k for k, ing in self._ingredients.items() if ing == med.ingredients])
        return med

    def _from_snapshot(self, med: Med) -> str | None:
        """Fills `med` from label names; returns why it could not."""
        try:
            candidates = self.index.catalog.search(med.name)["labels"] if 1 <= len(med.name) <= 80 else []
        except ApiError:
            candidates = []
        if not candidates:
            return "unknown_name"
        exact = [c for c in candidates if c["name"].casefold().strip() == med.name.casefold()]
        pool = exact or candidates
        sets = {self._ingredients[(c["id"], c["version"])] for c in pool}
        if len(sets) != 1:
            return "ambiguous_name"  # e.g. "Advil" matching "ADVIL COLD AND SINUS" too, with different ingredients
        med.ingredients = sets.pop()
        med.label = self._representative([(c["id"], c["version"]) for c in pool])
        return None

    def _representative(self, keys: list[tuple[str, str]]) -> dict | None:
        """One label to read for a product: adult over children's versions, then the one with the most to say about
        combinations (some snapshot records lack those sections), newest version, then a stable id order."""
        if not keys:
            return None
        def order(key):
            record = self.snapshot.records[key]
            name = next(iter(names(record)), "")
            said = sum(1 for _ in self._passages({"id": key[0], "version": key[1]}))
            return (bool(CHILD.search(name)), -said, -int(key[1]) if key[1].isdigit() else 0, key[0])
        key = min(keys, key=order)
        return {"id": key[0], "version": key[1], "name": next(iter(names(self.snapshot.records[key])), "Drug label")}

    # ----- reading labels ------------------------------------------------------------------------------------
    def _terms(self, med: Med, skip: frozenset[str]) -> list[tuple[int, str, str]]:
        """(priority, needle, how to say it in Chinese). Ingredient names beat class phrases."""
        terms = []
        for key in med.ingredients - skip:
            _, en, classes = INGREDIENTS.get(key, ([], [], []))
            terms += [(0, alias, ingredient_zh(key)) for alias in [key, *en]]
            for cls in classes:
                if all(cls not in INGREDIENTS.get(s, ([], [], []))[2] for s in skip):
                    zh, phrases = CLASSES[cls]
                    terms += [(1, phrase, zh) for phrase in phrases]
        return terms

    def _passages(self, label: dict, fields=INTERACTION_SECTIONS):
        for i in self.index.by_label.get((label["id"], label["version"]), []):
            passage = self.index.passages[i]
            if passage.field in fields:
                yield passage

    def _citation(self, label: dict, passage, at: int) -> dict:
        text = passage.text
        start = max(0, min(at, len(text)) - EXCERPT_CHARS // 3)
        excerpt = ("…" if start else "") + text[start:start + EXCERPT_CHARS].strip() + \
                  ("…" if start + EXCERPT_CHARS < len(text) else "")
        return {"label": label["name"], "label_id": label["id"], "version": label["version"],
                "section": passage.section, "section_zh": SECTION_ZH.get(passage.field, passage.section),
                "passage_id": passage.id, "excerpt": excerpt,
                "source_url": source_url(label["id"], label["version"]) if self.snapshot.public else None}

    @staticmethod
    def _locate(text: str, phrase: str, containing: bool = False) -> int | None:
        """Character offset in `text` of the best occurrence of `phrase` (whole words, any punctuation between).

        Skipped: mentions inside an allergy statement ("allergic to aspirin", "an antihistamine containing
        hydroxyzine" after "allergic reaction to") and negated ones ("no clinically significant effect ... warfarin"),
        since neither says the combination is a problem. Preferred: occurrences after "other", as in "other drugs
        containing NSAIDs". With `containing`, only occurrences within 100 characters after "contain" count.
        """
        hits = []
        for match in _pattern(phrase).finditer(text):
            before = text[max(0, match.start() - 160):match.start()].casefold()
            clause = re.split(r"[.;!?•]", before)[-1]
            if "allerg" in clause or NEGATED.search(clause):
                continue
            if containing and "contain" not in before[-100:]:
                continue
            hits.append((match.start(), " other " in f" {before[-80:]} "))
        if not hits:
            return None
        preferred = [at for at, other in hits if other]
        return preferred[0] if preferred else hits[0][0]

    def _scan(self, label: dict | None, terms, containing: bool = False) -> list[tuple[tuple, object, int, str]]:
        if label is None or not terms:
            return []
        found = []
        for passage in self._passages(label):
            best = None
            for priority, needle, said in terms:
                at = self._locate(passage.text, needle, containing)
                if at is not None and (best is None or priority < best[0]):
                    best = (priority, at, said)
            if best:
                rank = (INTERACTION_SECTIONS.index(passage.field), best[0])
                found.append((rank, passage, best[1], best[2]))
        return sorted(found, key=lambda f: f[0])

    # ----- the review ----------------------------------------------------------------------------------------
    def review(self, medication: str, medications: list[dict], taken_at: int | None = None) -> dict:
        taken_at = taken_at or int(time.time() * 1000)
        new = self.resolve(medication)
        result = {"status": "ok", "medication": new.view(), "checked": [], "unresolved": [], "not_recent": [],
                  "alerts": [], "severity": None, "note": NOTE}
        if new.problem:
            result.update(status="unresolved_medication", reason=new.problem)
            return result
        seen = set()
        for record in medications:
            name = str(record.get("name") or "").strip()
            if not name or same_name(name) == same_name(new.name) or same_name(name) in seen:
                continue  # the same product again is a dosing question, not a combination
            seen.add(same_name(name))
            last = record.get("last_taken_at")
            gap = abs(taken_at - last) if isinstance(last, (int, float)) else 0
            if gap > INTERACTION_WINDOW_MS:
                result["not_recent"].append(name)
                continue
            other = self.resolve(name, last)
            if other.problem:
                result["unresolved"].append(name)
                continue
            result["checked"].append(other.view())
            alert = self._pair(new, other, gap)
            if alert:
                result["alerts"].append(alert)
        result["alerts"].sort(key=lambda a: a["severity"] != "high")
        if result["alerts"]:
            result["severity"] = result["alerts"][0]["severity"]
        return result

    def _pair(self, new: Med, other: Med, gap: int) -> dict | None:
        findings: list[Finding] = []
        shared = new.ingredients & other.ingredients
        if shared and gap <= DUPLICATE_WINDOW_MS:
            said = "、".join(ingredient_zh(s) for s in sorted(shared))
            summary = (f"{new.name} 和 {other.name} 含有相同成分（{said}），24 小时内一起用可能超过每日最大剂量；"
                       f"如果这是同一种药的两种叫法，可以忽略。")
            for med in (new, other):
                terms = [(0, s, ingredient_zh(s)) for s in shared]
                hits = self._scan(med.label, terms, containing=True)
                if hits:
                    rank, passage, at, _ = hits[0]
                    findings.append(Finding((0, *rank), summary, self._citation(med.label, passage, at), True,
                                            "duplicate_ingredient"))
                    break
            else:
                label = new.label or other.label
                passage = next(self._passages(label, ("active_ingredient",)), None) if label else None
                findings.append(Finding((0, 99, 0), summary, self._citation(label, passage, 0) if passage else {},
                                        True, "duplicate_ingredient"))
        # Each label read for the other product's ingredients and classes, minus what they share (handled above).
        for reader, mentioned in ((new, other), (other, new)):
            hits = self._scan(reader.label, self._terms(mentioned, shared))
            if hits:
                rank, passage, at, said = hits[0]
                section = SECTION_ZH.get(passage.field, passage.section)
                who = said if said == mentioned.name else f"{said}（{mentioned.name}）"
                summary = f"{reader.label['name']} 的说明书在「{section}」里提到了{who}。"
                findings.append(Finding((1, *rank), summary, self._citation(reader.label, passage, at),
                                        passage.field in HIGH_SECTIONS, "label_warning"))
        if not findings:
            return None
        findings.sort(key=lambda f: f.rank)
        findings = findings[:MAX_FINDINGS]
        return {"with": other.name, "severity": "high" if any(f.high for f in findings) else "moderate",
                "kinds": sorted({f.kind for f in findings}),
                "findings": [{"summary": f.summary, "citation": f.citation} for f in findings]}
