# Multi-stage build: compile with Maven, run on a slim JRE so the final image doesn't carry the JDK/build cache.
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /build
# Cache dependencies separately from source so an app-only change skips the download step.
COPY pom.xml .
RUN mvn -B -q dependency:go-offline
COPY src ./src
RUN mvn -B -q package -DskipTests

FROM eclipse-temurin:21-jre-alpine
RUN addgroup -S medtrack && adduser -S medtrack -G medtrack
WORKDIR /app
COPY --from=build /build/target/medsync-gateway-*.jar app.jar
USER medtrack
EXPOSE 8081
ENTRYPOINT ["java", "-jar", "app.jar"]
