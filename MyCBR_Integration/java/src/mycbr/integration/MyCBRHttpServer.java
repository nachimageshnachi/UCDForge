package mycbr.integration;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import de.dfki.mycbr.core.ICaseBase;
import de.dfki.mycbr.core.Project;
import de.dfki.mycbr.core.casebase.Instance;
import de.dfki.mycbr.core.model.Concept;
import de.dfki.mycbr.core.model.IntegerDesc;
import de.dfki.mycbr.core.model.StringDesc;
import de.dfki.mycbr.core.retrieval.Retrieval;
import de.dfki.mycbr.core.similarity.AmalgamationFct;
import de.dfki.mycbr.core.similarity.IntegerFct;
import de.dfki.mycbr.core.similarity.Similarity;
import de.dfki.mycbr.core.similarity.StringFct;
import de.dfki.mycbr.core.similarity.config.AmalgamationConfig;
import de.dfki.mycbr.core.similarity.config.DistanceConfig;
import de.dfki.mycbr.core.similarity.config.NumberConfig;
import de.dfki.mycbr.core.similarity.config.StringConfig;
import de.dfki.mycbr.util.Pair;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.Executors;

public final class MyCBRHttpServer {
    private static final int DEFAULT_PORT = 8099;

    public static void main(String[] args) throws Exception {
        int port = DEFAULT_PORT;
        if (args.length >= 1 && args[0] != null && !args[0].isBlank()) {
            port = Integer.parseInt(args[0]);
        }
        Path runtimeRoot = args.length >= 2 && args[1] != null && !args[1].isBlank()
            ? Paths.get(args[1]).toAbsolutePath().normalize()
            : Paths.get("MyCBR_Integration", "runtime").toAbsolutePath().normalize();

        ServiceState state = new ServiceState(runtimeRoot);
        state.bootstrap();

        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
        server.setExecutor(Executors.newCachedThreadPool());
        server.createContext("/health", exchange -> handle(exchange, ex -> state.health()));
        server.createContext("/cases", exchange -> handle(exchange, ex -> state.listCases()));
        server.createContext("/cases/reset", exchange -> handle(exchange, ex -> state.reset()));
        server.createContext("/cases/import", exchange -> handle(exchange, ex -> {
            Map<String, Object> payload = readObjectBody(ex);
            List<UcdCase> imported = parseCaseList(payload.get("cases"));
            boolean replace = asBoolean(payload.getOrDefault("replace", Boolean.TRUE));
            return state.importCases(imported, replace);
        }));
        server.createContext("/cases/add", exchange -> handle(exchange, ex -> {
            Map<String, Object> payload = readObjectBody(ex);
            Object value = payload.containsKey("case") ? payload.get("case") : payload;
            return state.addCase(UcdCase.fromObject(value));
        }));
        server.createContext("/query", exchange -> handle(exchange, ex -> {
            Map<String, Object> payload = readObjectBody(ex);
            Object queryValue = payload.containsKey("query") ? payload.get("query") : payload;
            UcdCase queryCase = UcdCase.fromObject(queryValue);
            String profile = asString(payload.getOrDefault("profile", "balanced"));
            int k = asInt(payload.getOrDefault("k", 5), 5);
            double minSimilarity = asDouble(payload.getOrDefault("min_similarity", 0.0), 0.0);
            return state.query(queryCase, profile, k, minSimilarity);
        }));

        server.start();
        System.out.println("MyCBR HTTP service running on http://127.0.0.1:" + port + " using store " + state.storePath());
    }

    @FunctionalInterface
    private interface ExchangeAction {
        Object run(HttpExchange exchange) throws Exception;
    }

    private static void handle(HttpExchange exchange, ExchangeAction action) throws IOException {
        try {
            addCors(exchange);
            if ("OPTIONS".equalsIgnoreCase(exchange.getRequestMethod())) {
                exchange.sendResponseHeaders(204, -1);
                exchange.close();
                return;
            }
            Object payload = action.run(exchange);
            writeJson(exchange, 200, payload);
        } catch (Exception exc) {
            Map<String, Object> error = new LinkedHashMap<>();
            error.put("status", "error");
            error.put("message", exc.getMessage() == null ? exc.toString() : exc.getMessage());
            writeJson(exchange, 500, error);
        }
    }

    private static void addCors(HttpExchange exchange) {
        exchange.getResponseHeaders().set("Access-Control-Allow-Origin", "*");
        exchange.getResponseHeaders().set("Access-Control-Allow-Headers", "Content-Type");
        exchange.getResponseHeaders().set("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
    }

    private static void writeJson(HttpExchange exchange, int status, Object payload) throws IOException {
        byte[] bytes = MiniJson.stringify(payload).getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream output = exchange.getResponseBody()) {
            output.write(bytes);
        }
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> readObjectBody(HttpExchange exchange) throws Exception {
        try (InputStream stream = exchange.getRequestBody()) {
            String body = new String(stream.readAllBytes(), StandardCharsets.UTF_8).trim();
            if (body.isEmpty()) {
                return new LinkedHashMap<>();
            }
            Object parsed = MiniJson.parse(body);
            if (!(parsed instanceof Map)) {
                throw new IllegalArgumentException("JSON object body expected");
            }
            return (Map<String, Object>) parsed;
        }
    }

    private static List<UcdCase> parseCaseList(Object value) {
        List<UcdCase> cases = new ArrayList<>();
        if (!(value instanceof List<?> listValue)) {
            return cases;
        }
        for (Object item : listValue) {
            cases.add(UcdCase.fromObject(item));
        }
        return cases;
    }

    private static String asString(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }

    private static boolean asBoolean(Object value) {
        if (value instanceof Boolean boolValue) {
            return boolValue;
        }
        return "true".equalsIgnoreCase(asString(value));
    }

    private static int asInt(Object value, int fallback) {
        if (value instanceof Number number) {
            return number.intValue();
        }
        try {
            return Integer.parseInt(asString(value));
        } catch (Exception exc) {
            return fallback;
        }
    }

    private static double asDouble(Object value, double fallback) {
        if (value instanceof Number number) {
            return number.doubleValue();
        }
        try {
            return Double.parseDouble(asString(value));
        } catch (Exception exc) {
            return fallback;
        }
    }

    private static double round(double value) {
        return Math.round(value * 10000.0) / 10000.0;
    }

    private static final class ServiceState {
        private final Path runtimeRoot;
        private final Path storePath;
        private final List<UcdCase> storedCases = new ArrayList<>();
        private final Map<String, UcdCase> caseIndex = new LinkedHashMap<>();
        private final Map<String, AmalgamationFct> profiles = new LinkedHashMap<>();

        private Project project;
        private Concept concept;
        private ICaseBase caseBase;

        private StringDesc systemNameDesc;
        private StringDesc descriptionDesc;
        private StringDesc primaryDomainDesc;
        private StringDesc systemKindDesc;
        private StringDesc primaryActorsDesc;
        private StringDesc secondaryActorsDesc;
        private StringDesc useCasesDesc;
        private StringDesc hasIncludeDesc;
        private StringDesc hasExtendDesc;
        private StringDesc hasGeneralizationDesc;
        private StringDesc caseOriginDesc;
        private IntegerDesc primaryActorCountDesc;
        private IntegerDesc secondaryActorCountDesc;
        private IntegerDesc useCaseCountDesc;
        private IntegerDesc relationshipCountDesc;
        private StringFct exactText;
        private StringFct systemNameLev;
        private StringFct descriptionNgram;
        private StringFct actorsNgram;
        private StringFct secondaryActorsNgram;
        private StringFct useCasesNgram;
        private StringFct systemKindExact;
        private StringFct hasIncludeExact;
        private StringFct hasExtendExact;
        private StringFct hasGeneralizationExact;
        private StringFct caseOriginExact;
        private IntegerFct strictPrimaryActorCount;
        private IntegerFct loosePrimaryActorCount;
        private IntegerFct strictSecondaryActorCount;
        private IntegerFct looseSecondaryActorCount;
        private IntegerFct strictUseCaseCount;
        private IntegerFct looseUseCaseCount;
        private IntegerFct strictRelationshipCount;
        private IntegerFct looseRelationshipCount;

        private ServiceState(Path runtimeRoot) {
            this.runtimeRoot = runtimeRoot;
            this.storePath = runtimeRoot.resolve("service_case_store.json");
        }

        private synchronized void bootstrap() throws Exception {
            Files.createDirectories(runtimeRoot);
            if (Files.exists(storePath)) {
                Object parsed = MiniJson.parse(Files.readString(storePath, StandardCharsets.UTF_8));
                if (parsed instanceof List<?> listValue) {
                    for (Object item : listValue) {
                        storedCases.add(UcdCase.fromObject(item));
                    }
                }
            }
            rebuildProject();
        }

        private synchronized Map<String, Object> health() {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("status", "ok");
            out.put("project_name", "UCD_MyCBR_Integration");
            out.put("case_count", storedCases.size());
            out.put("store_path", storePath.toString());
            out.put("profiles", new ArrayList<>(profiles.keySet()));
            return out;
        }

        private synchronized Map<String, Object> listCases() {
            List<Object> items = new ArrayList<>();
            for (UcdCase item : storedCases) {
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("case_key", item.caseKey);
                row.put("case_id", item.caseId);
                row.put("title", item.title);
                row.put("system_name", item.systemName);
                row.put("source", item.source);
                row.put("domains", item.domains);
                row.put("use_case_count", item.useCases.size());
                items.add(row);
            }
            Map<String, Object> out = health();
            out.put("cases", items);
            return out;
        }

        private synchronized Map<String, Object> reset() throws Exception {
            storedCases.clear();
            persist();
            rebuildProject();
            return health();
        }

        private synchronized Map<String, Object> importCases(List<UcdCase> incoming, boolean replace) throws Exception {
            LinkedHashMap<String, UcdCase> merged = new LinkedHashMap<>();
            if (!replace) {
                for (UcdCase item : storedCases) {
                    merged.put(item.caseKey, item);
                }
            }
            for (UcdCase item : incoming) {
                merged.put(item.caseKey, item);
            }
            storedCases.clear();
            storedCases.addAll(merged.values());
            persist();
            rebuildProject();
            Map<String, Object> out = health();
            out.put("imported", incoming.size());
            out.put("replace", replace);
            return out;
        }

        private synchronized Map<String, Object> addCase(UcdCase item) throws Exception {
            LinkedHashMap<String, UcdCase> merged = new LinkedHashMap<>();
            for (UcdCase existing : storedCases) {
                merged.put(existing.caseKey, existing);
            }
            merged.put(item.caseKey, item);
            storedCases.clear();
            storedCases.addAll(merged.values());
            persist();
            rebuildProject();
            Map<String, Object> out = health();
            out.put("added_case", item.toMap());
            return out;
        }

        private synchronized Map<String, Object> query(UcdCase queryCase, String profileName, int k, double minSimilarity) throws Exception {
            if (storedCases.isEmpty()) {
                Map<String, Object> out = health();
                out.put("query_profile", normalizeProfile(profileName));
                out.put("results", List.of());
                return out;
            }
            concept.setActiveAmalgamFct(profiles.get(normalizeProfile(profileName)));
            Retrieval retrieval = new Retrieval(concept, caseBase);
            retrieval.setK(Math.max(1, Math.min(k, storedCases.size())));
            Instance queryInstance = retrieval.resetQuery();
            if (queryInstance == null) {
                queryInstance = retrieval.getQueryInstance();
            }
            if (queryInstance == null) {
                throw new IllegalStateException("Could not initialize query instance");
            }
            queryInstance.reset();
            applyInstanceValues(queryInstance, queryCase);
            retrieval.start();

            List<Object> rows = new ArrayList<>();
            for (Pair<Instance, Similarity> pair : retrieval.getResult()) {
                UcdCase match = caseIndex.get(pair.getFirst().getName());
                if (match == null) {
                    continue;
                }
                double similarity = pair.getSecond() == null ? 0.0 : pair.getSecond().getValue();
                if (similarity + 1e-9 < minSimilarity) {
                    continue;
                }
                Map<String, Object> row = match.toMap();
                row.put("similarity", round(similarity));
                rows.add(row);
            }
            rows.sort((left, right) -> Double.compare(
                ((Number) ((Map<?, ?>) right).get("similarity")).doubleValue(),
                ((Number) ((Map<?, ?>) left).get("similarity")).doubleValue()
            ));

            Map<String, Object> out = health();
            out.put("query_profile", normalizeProfile(profileName));
            out.put("query_case", queryCase.toMap());
            out.put("results", rows);
            return out;
        }

        private String normalizeProfile(String raw) {
            String key = asString(raw).toLowerCase(Locale.ROOT);
            return profiles.containsKey(key) ? key : "balanced";
        }

        private void rebuildProject() throws Exception {
            caseIndex.clear();
            profiles.clear();
            project = new Project();
            concept = project.createTopConcept("UseCaseDiagram");
            caseBase = project.createDefaultCB("UseCaseCaseBase");

            systemNameDesc = new StringDesc(concept, "system_name_text");
            descriptionDesc = new StringDesc(concept, "description_text");
            primaryDomainDesc = new StringDesc(concept, "primary_domain");
            systemKindDesc = new StringDesc(concept, "system_kind");
            primaryActorsDesc = new StringDesc(concept, "primary_actors_text");
            secondaryActorsDesc = new StringDesc(concept, "secondary_actors_text");
            useCasesDesc = new StringDesc(concept, "use_cases_text");
            hasIncludeDesc = new StringDesc(concept, "has_include");
            hasExtendDesc = new StringDesc(concept, "has_extend");
            hasGeneralizationDesc = new StringDesc(concept, "has_generalization");
            caseOriginDesc = new StringDesc(concept, "case_origin");
            primaryActorCountDesc = new IntegerDesc(concept, "primary_actor_count", 0, 500);
            secondaryActorCountDesc = new IntegerDesc(concept, "secondary_actor_count", 0, 500);
            useCaseCountDesc = new IntegerDesc(concept, "use_case_count", 0, 1000);
            relationshipCountDesc = new IntegerDesc(concept, "relationship_count", 0, 1000);

            systemNameLev = createStringFct(systemNameDesc, StringConfig.LEVENSHTEIN, "system_name_levenshtein");
            descriptionNgram = createStringFct(descriptionDesc, StringConfig.NGRAM, "description_ngram");
            exactText = createStringFct(primaryDomainDesc, StringConfig.EQUALITY, "primary_domain_exact");
            systemKindExact = createStringFct(systemKindDesc, StringConfig.EQUALITY, "system_kind_exact");
            actorsNgram = createStringFct(primaryActorsDesc, StringConfig.NGRAM, "primary_actors_ngram");
            secondaryActorsNgram = createStringFct(secondaryActorsDesc, StringConfig.NGRAM, "secondary_actors_ngram");
            useCasesNgram = createStringFct(useCasesDesc, StringConfig.NGRAM, "use_cases_ngram");
            hasIncludeExact = createStringFct(hasIncludeDesc, StringConfig.EQUALITY, "has_include_exact");
            hasExtendExact = createStringFct(hasExtendDesc, StringConfig.EQUALITY, "has_extend_exact");
            hasGeneralizationExact = createStringFct(hasGeneralizationDesc, StringConfig.EQUALITY, "has_generalization_exact");
            caseOriginExact = createStringFct(caseOriginDesc, StringConfig.EQUALITY, "case_origin_exact");

            strictPrimaryActorCount = createIntegerFct(primaryActorCountDesc, "primary_actor_count_strict", 1.5);
            loosePrimaryActorCount = createIntegerFct(primaryActorCountDesc, "primary_actor_count_loose", 4.0);
            strictSecondaryActorCount = createIntegerFct(secondaryActorCountDesc, "secondary_actor_count_strict", 1.5);
            looseSecondaryActorCount = createIntegerFct(secondaryActorCountDesc, "secondary_actor_count_loose", 4.0);
            strictUseCaseCount = createIntegerFct(useCaseCountDesc, "use_case_count_strict", 1.5);
            looseUseCaseCount = createIntegerFct(useCaseCountDesc, "use_case_count_loose", 4.0);
            strictRelationshipCount = createIntegerFct(relationshipCountDesc, "relationship_count_strict", 1.5);
            looseRelationshipCount = createIntegerFct(relationshipCountDesc, "relationship_count_loose", 4.0);
            AmalgamationFct balanced = concept.addAmalgamationFct(AmalgamationConfig.WEIGHTED_SUM, "balanced", true);
            bind(balanced, systemNameDesc, systemNameLev, 2.5);
            bind(balanced, descriptionDesc, descriptionNgram, 2.0);
            bind(balanced, primaryDomainDesc, exactText, 1.2);
            bind(balanced, systemKindDesc, systemKindExact, 1.0);
            bind(balanced, primaryActorsDesc, actorsNgram, 1.8);
            bind(balanced, secondaryActorsDesc, secondaryActorsNgram, 1.2);
            bind(balanced, useCasesDesc, useCasesNgram, 2.6);
            bind(balanced, primaryActorCountDesc, loosePrimaryActorCount, 1.1);
            bind(balanced, secondaryActorCountDesc, looseSecondaryActorCount, 0.8);
            bind(balanced, useCaseCountDesc, looseUseCaseCount, 1.4);
            bind(balanced, relationshipCountDesc, looseRelationshipCount, 0.9);
            bind(balanced, hasIncludeDesc, hasIncludeExact, 0.5);
            bind(balanced, hasExtendDesc, hasExtendExact, 0.5);
            bind(balanced, hasGeneralizationDesc, hasGeneralizationExact, 0.5);
            bind(balanced, caseOriginDesc, caseOriginExact, 0.2);
            profiles.put("balanced", balanced);

            AmalgamationFct structure = concept.addAmalgamationFct(AmalgamationConfig.WEIGHTED_SUM, "structure", false);
            bind(structure, systemNameDesc, systemNameLev, 1.0);
            bind(structure, primaryDomainDesc, exactText, 1.5);
            bind(structure, systemKindDesc, systemKindExact, 1.5);
            bind(structure, primaryActorCountDesc, strictPrimaryActorCount, 1.8);
            bind(structure, secondaryActorCountDesc, strictSecondaryActorCount, 1.8);
            bind(structure, useCaseCountDesc, strictUseCaseCount, 2.5);
            bind(structure, relationshipCountDesc, strictRelationshipCount, 2.0);
            bind(structure, hasIncludeDesc, hasIncludeExact, 1.2);
            bind(structure, hasExtendDesc, hasExtendExact, 1.2);
            bind(structure, hasGeneralizationDesc, hasGeneralizationExact, 1.2);
            profiles.put("structure", structure);

            AmalgamationFct text = concept.addAmalgamationFct(AmalgamationConfig.WEIGHTED_SUM, "text", false);
            bind(text, systemNameDesc, systemNameLev, 2.0);
            bind(text, descriptionDesc, descriptionNgram, 3.0);
            bind(text, primaryActorsDesc, actorsNgram, 2.0);
            bind(text, secondaryActorsDesc, secondaryActorsNgram, 1.3);
            bind(text, useCasesDesc, useCasesNgram, 3.2);
            bind(text, primaryDomainDesc, exactText, 0.8);
            bind(text, systemKindDesc, systemKindExact, 0.6);
            profiles.put("text", text);

            concept.setActiveAmalgamFct(balanced);
            for (UcdCase item : storedCases) {
                Instance instance = concept.addInstance(item.caseKey);
                applyInstanceValues(instance, item);
                caseBase.addCase(instance);
                caseIndex.put(item.caseKey, item);
            }
        }

        private void bind(AmalgamationFct amalgam, de.dfki.mycbr.core.model.AttributeDesc desc, Object fct, double weight) {
            amalgam.setActive(desc, true);
            amalgam.setActiveFct(desc, fct);
            amalgam.setWeight(desc, weight);
        }

        private StringFct createStringFct(StringDesc desc, StringConfig config, String name) throws Exception {
            StringFct function = desc.addStringFct(config, name, true);
            function.setCaseSensitive(false);
            if (config == StringConfig.NGRAM) {
                function.setN(3);
            }
            return function;
        }

        private IntegerFct createIntegerFct(IntegerDesc desc, String name, double polynomial) {
            IntegerFct function = desc.addIntegerFct(name, true);
            function.setDistanceFct(DistanceConfig.DIFFERENCE);
            function.setFunctionTypeL(NumberConfig.CONSTANT);
            function.setFunctionParameterL(1.0);
            function.setFunctionTypeR(NumberConfig.POLYNOMIAL_WITH);
            function.setFunctionParameterR(polynomial);
            return function;
        }

        private void applyInstanceValues(Instance instance, UcdCase item) throws Exception {
            instance.addAttribute(systemNameDesc, item.systemName);
            instance.addAttribute(descriptionDesc, item.description);
            instance.addAttribute(primaryDomainDesc, item.primaryDomain());
            instance.addAttribute(systemKindDesc, item.systemKind());
            instance.addAttribute(primaryActorsDesc, item.joinedPrimaryActors());
            instance.addAttribute(secondaryActorsDesc, item.joinedSecondaryActors());
            instance.addAttribute(useCasesDesc, item.joinedUseCases());
            instance.addAttribute(primaryActorCountDesc, item.primaryActors.size());
            instance.addAttribute(secondaryActorCountDesc, item.secondaryActors.size());
            instance.addAttribute(useCaseCountDesc, item.useCases.size());
            instance.addAttribute(relationshipCountDesc, item.relationshipCount());
            instance.addAttribute(hasIncludeDesc, item.hasRelationship("include") ? "yes" : "no");
            instance.addAttribute(hasExtendDesc, item.hasRelationship("extend") ? "yes" : "no");
            instance.addAttribute(hasGeneralizationDesc, item.hasRelationship("generalization") ? "yes" : "no");
            instance.addAttribute(caseOriginDesc, item.source);
        }

        private void persist() throws Exception {
            List<Object> payload = new ArrayList<>();
            for (UcdCase item : storedCases) {
                payload.add(item.toMap());
            }
            Files.writeString(storePath, MiniJson.stringify(payload), StandardCharsets.UTF_8);
        }

        private String storePath() {
            return storePath.toString();
        }
    }

    private static final class UcdCase {
        private final String caseKey;
        private final String caseId;
        private final String source;
        private final String title;
        private final String systemName;
        private final String description;
        private final List<String> domains;
        private final List<String> primaryActors;
        private final List<String> secondaryActors;
        private final List<String> useCases;
        private final List<String> relationshipTypes;

        private UcdCase(String caseKey, String caseId, String source, String title, String systemName, String description,
                        List<String> domains, List<String> primaryActors, List<String> secondaryActors,
                        List<String> useCases, List<String> relationshipTypes) {
            this.caseKey = caseKey;
            this.caseId = caseId;
            this.source = source == null || source.isBlank() ? "unknown" : source.trim();
            this.title = title == null ? "" : title.trim();
            this.systemName = systemName == null ? "" : systemName.trim();
            this.description = description == null ? "" : description.trim();
            this.domains = uniqueStrings(domains);
            this.primaryActors = uniqueStrings(primaryActors);
            this.secondaryActors = uniqueStrings(secondaryActors);
            this.useCases = uniqueStrings(useCases);
            this.relationshipTypes = uniqueStrings(relationshipTypes);
        }

        @SuppressWarnings("unchecked")
        private static UcdCase fromObject(Object value) {
            if (!(value instanceof Map<?, ?> rawMap)) {
                throw new IllegalArgumentException("Case payload must be a JSON object");
            }
            Map<String, Object> map = (Map<String, Object>) rawMap;
            String caseId = asString(map.get("case_id"));
            String systemName = asString(map.get("system_name"));
            String title = asString(map.get("title"));
            String source = asString(map.get("source"));
            String caseKey = asString(map.get("case_key"));
            if (caseKey.isBlank()) {
                String seed = !caseId.isBlank() ? caseId : (!title.isBlank() ? title : UUID.randomUUID().toString());
                caseKey = (source.isBlank() ? "case" : source) + "-" + seed.replaceAll("[^A-Za-z0-9_-]", "_");
            }
            List<String> relationshipTypes = stringList(map.get("relationship_types"));
            if (relationshipTypes.isEmpty() && map.get("relationships") instanceof List<?> rawRelationships) {
                for (Object rel : rawRelationships) {
                    if (rel instanceof Map<?, ?> relMap) {
                        relationshipTypes.add(asString(((Map<String, Object>) relMap).get("relationship_type")));
                    }
                }
            }
            return new UcdCase(
                caseKey,
                caseId,
                source,
                title,
                systemName,
                asString(map.get("description")),
                stringList(map.get("domains")),
                stringList(map.get("primary_actors")),
                stringList(map.get("secondary_actors")),
                stringList(map.get("use_cases")),
                relationshipTypes
            );
        }
        private Map<String, Object> toMap() {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("case_key", caseKey);
            out.put("case_id", caseId);
            out.put("source", source);
            out.put("title", title);
            out.put("system_name", systemName);
            out.put("description", description);
            out.put("domains", domains);
            out.put("primary_actors", primaryActors);
            out.put("secondary_actors", secondaryActors);
            out.put("use_cases", useCases);
            out.put("relationship_types", relationshipTypes);
            out.put("relationship_count", relationshipCount());
            return out;
        }

        private String primaryDomain() {
            return domains.isEmpty() ? "Undefined" : domains.get(0);
        }

        private String systemKind() {
            String raw = systemName.isBlank() ? title : systemName;
            if (raw.isBlank()) {
                return "System";
            }
            String[] tokens = raw.trim().split("\\s+");
            return tokens[tokens.length - 1];
        }

        private int relationshipCount() {
            return relationshipTypes.size();
        }

        private boolean hasRelationship(String relationshipType) {
            String normalized = relationshipType.toLowerCase(Locale.ROOT);
            for (String item : relationshipTypes) {
                String raw = item.toLowerCase(Locale.ROOT);
                if (raw.equals(normalized)) {
                    return true;
                }
                if (normalized.equals("generalization") && raw.equals("generalisation")) {
                    return true;
                }
            }
            return false;
        }

        private String joinedPrimaryActors() {
            return String.join(" | ", primaryActors);
        }

        private String joinedSecondaryActors() {
            return String.join(" | ", secondaryActors);
        }

        private String joinedUseCases() {
            return String.join(" | ", useCases);
        }

        private static List<String> stringList(Object value) {
            List<String> out = new ArrayList<>();
            if (value instanceof List<?> listValue) {
                for (Object item : listValue) {
                    String text = asString(item);
                    if (!text.isBlank()) {
                        out.add(text);
                    }
                }
            }
            return uniqueStrings(out);
        }

        private static List<String> uniqueStrings(Collection<String> values) {
            LinkedHashSet<String> seen = new LinkedHashSet<>();
            for (String raw : values) {
                String text = raw == null ? "" : raw.trim();
                if (!text.isBlank()) {
                    seen.add(text);
                }
            }
            return new ArrayList<>(seen);
        }
    }

    private static final class MiniJson {
        private MiniJson() {
        }

        private static Object parse(String text) {
            Parser parser = new Parser(text);
            Object value = parser.parseValue();
            parser.skipWhitespace();
            if (!parser.isDone()) {
                throw new IllegalArgumentException("Unexpected trailing JSON content");
            }
            return value;
        }

        private static String stringify(Object value) {
            StringBuilder builder = new StringBuilder();
            writeValue(builder, value);
            return builder.toString();
        }

        @SuppressWarnings("unchecked")
        private static void writeValue(StringBuilder builder, Object value) {
            if (value == null) {
                builder.append("null");
            } else if (value instanceof String stringValue) {
                builder.append('"').append(escape(stringValue)).append('"');
            } else if (value instanceof Number || value instanceof Boolean) {
                builder.append(value);
            } else if (value instanceof Map<?, ?> mapValue) {
                builder.append('{');
                boolean first = true;
                for (Map.Entry<String, Object> entry : ((Map<String, Object>) mapValue).entrySet()) {
                    if (!first) {
                        builder.append(',');
                    }
                    first = false;
                    builder.append('"').append(escape(entry.getKey())).append('"').append(':');
                    writeValue(builder, entry.getValue());
                }
                builder.append('}');
            } else if (value instanceof Iterable<?> iterable) {
                builder.append('[');
                boolean first = true;
                for (Object item : iterable) {
                    if (!first) {
                        builder.append(',');
                    }
                    first = false;
                    writeValue(builder, item);
                }
                builder.append(']');
            } else {
                builder.append('"').append(escape(String.valueOf(value))).append('"');
            }
        }

        private static String escape(String value) {
            StringBuilder out = new StringBuilder();
            for (int i = 0; i < value.length(); i++) {
                char ch = value.charAt(i);
                switch (ch) {
                    case '"' -> out.append("\\\"");
                    case '\\' -> out.append("\\\\");
                    case '\b' -> out.append("\\b");
                    case '\f' -> out.append("\\f");
                    case '\n' -> out.append("\\n");
                    case '\r' -> out.append("\\r");
                    case '\t' -> out.append("\\t");
                    default -> {
                        if (ch < 0x20) {
                            out.append(String.format("\\u%04x", (int) ch));
                        } else {
                            out.append(ch);
                        }
                    }
                }
            }
            return out.toString();
        }

        private static final class Parser {
            private final String text;
            private int index;

            private Parser(String text) {
                this.text = text == null ? "" : text;
            }

            private boolean isDone() {
                return index >= text.length();
            }

            private void skipWhitespace() {
                while (!isDone() && Character.isWhitespace(text.charAt(index))) {
                    index++;
                }
            }

            private Object parseValue() {
                skipWhitespace();
                if (isDone()) {
                    throw new IllegalArgumentException("Unexpected end of JSON input");
                }
                return switch (text.charAt(index)) {
                    case '{' -> parseObject();
                    case '[' -> parseArray();
                    case '"' -> parseString();
                    case 't' -> parseTrue();
                    case 'f' -> parseFalse();
                    case 'n' -> parseNull();
                    default -> parseNumber();
                };
            }

            private Map<String, Object> parseObject() {
                LinkedHashMap<String, Object> out = new LinkedHashMap<>();
                expect('{');
                skipWhitespace();
                if (peek('}')) {
                    expect('}');
                    return out;
                }
                while (true) {
                    String key = parseString();
                    expect(':');
                    out.put(key, parseValue());
                    skipWhitespace();
                    if (peek('}')) {
                        expect('}');
                        return out;
                    }
                    expect(',');
                }
            }

            private List<Object> parseArray() {
                List<Object> out = new ArrayList<>();
                expect('[');
                skipWhitespace();
                if (peek(']')) {
                    expect(']');
                    return out;
                }
                while (true) {
                    out.add(parseValue());
                    skipWhitespace();
                    if (peek(']')) {
                        expect(']');
                        return out;
                    }
                    expect(',');
                }
            }
            private String parseString() {
                expect('"');
                StringBuilder out = new StringBuilder();
                while (!isDone()) {
                    char ch = text.charAt(index++);
                    if (ch == '"') {
                        return out.toString();
                    }
                    if (ch == '\\') {
                        if (isDone()) {
                            throw new IllegalArgumentException("Invalid JSON escape sequence");
                        }
                        char esc = text.charAt(index++);
                        switch (esc) {
                            case '"' -> out.append('"');
                            case '\\' -> out.append('\\');
                            case '/' -> out.append('/');
                            case 'b' -> out.append('\b');
                            case 'f' -> out.append('\f');
                            case 'n' -> out.append('\n');
                            case 'r' -> out.append('\r');
                            case 't' -> out.append('\t');
                            case 'u' -> {
                                if (index + 4 > text.length()) {
                                    throw new IllegalArgumentException("Invalid unicode escape");
                                }
                                out.append((char) Integer.parseInt(text.substring(index, index + 4), 16));
                                index += 4;
                            }
                            default -> throw new IllegalArgumentException("Unsupported JSON escape: \\" + esc);
                        }
                    } else {
                        out.append(ch);
                    }
                }
                throw new IllegalArgumentException("Unterminated JSON string");
            }

            private Boolean parseTrue() {
                expectLiteral("true");
                return Boolean.TRUE;
            }

            private Boolean parseFalse() {
                expectLiteral("false");
                return Boolean.FALSE;
            }

            private Object parseNull() {
                expectLiteral("null");
                return null;
            }

            private Number parseNumber() {
                int start = index;
                if (peek('-')) {
                    index++;
                }
                while (!isDone() && Character.isDigit(text.charAt(index))) {
                    index++;
                }
                if (!isDone() && text.charAt(index) == '.') {
                    index++;
                    while (!isDone() && Character.isDigit(text.charAt(index))) {
                        index++;
                    }
                }
                if (!isDone() && (text.charAt(index) == 'e' || text.charAt(index) == 'E')) {
                    index++;
                    if (!isDone() && (text.charAt(index) == '+' || text.charAt(index) == '-')) {
                        index++;
                    }
                    while (!isDone() && Character.isDigit(text.charAt(index))) {
                        index++;
                    }
                }
                String value = text.substring(start, index);
                if (value.isEmpty() || value.equals("-")) {
                    throw new IllegalArgumentException("Invalid JSON number");
                }
                if (value.contains(".") || value.contains("e") || value.contains("E")) {
                    return Double.parseDouble(value);
                }
                try {
                    return Integer.parseInt(value);
                } catch (NumberFormatException exc) {
                    return Long.parseLong(value);
                }
            }

            private boolean peek(char expected) {
                return !isDone() && text.charAt(index) == expected;
            }

            private void expect(char expected) {
                skipWhitespace();
                if (isDone() || text.charAt(index) != expected) {
                    throw new IllegalArgumentException("Expected '" + expected + "' in JSON input");
                }
                index++;
            }

            private void expectLiteral(String literal) {
                if (!text.regionMatches(index, literal, 0, literal.length())) {
                    throw new IllegalArgumentException("Expected '" + literal + "' in JSON input");
                }
                index += literal.length();
            }
        }
    }
}
