# Requirements Document

## Introduction

This document specifies the requirements for the **MVP of the Kognit AI HSE Cognitive / LLM Chatbot Microservice** (`kognit-ai-hse-llm-api`), the third intelligence vector of the Kognit AI HSE Augmented Business Intelligence ecosystem.

The service is an independently deployable microservice consumed by the Kognit AI HSE React frontend. It exposes an HTTP API that receives natural-language Health, Safety and Environment (HSE) analytics questions, resolves them against the existing HSE PostgreSQL data warehouse star schema, and returns a concise natural-language answer.

Example interaction:

- Question: `"¿Cuántos accidentes hubo en la planta A el mes pasado?"`
- Answer: `"Se registraron 12 incidentes en la Planta A durante febrero de 2026."`

The agent workflow is a **controlled LangGraph state machine**, not a free-form ReAct loop: the node sequence is fixed, auditable, and every warehouse access passes through a non-LLM safety layer.

### Provenance Convention

Every requirement, assumption and glossary entry in this document carries a provenance tag so that the specification is traceable to its source:

| Tag | Meaning |
|---|---|
| **[Notion-confirmed: _page name_]** | Directly confirmed by the cited Notion page in the "Kognit AI HSE" workspace. |
| **[Repo-confirmed]** | Directly confirmed by reading the `kognit-ai-hse-llm-api` workspace files. |
| **[User-directed]** | Explicitly directed by the requester for this MVP; supersedes older documentation where noted. |
| **[Assumption]** | Reasonable working assumption made to keep the MVP buildable; requires confirmation. |
| **[Open question]** | Unresolved; recorded in §Open Questions. Not answered by invention. |
| **[New proposed requirement]** | Addition beyond the confirmed Notion backlog; requires Product Owner acceptance. |

Where a capability could not be verified against the authoritative warehouse schema, the requirement states that the capability is **not supported in the MVP** and that the assistant reports the metric as unavailable, rather than inventing a table, column, metric or dimension value.

### Authoritative Sources (precedence order)

1. **HSE Data Warehouse — Star Schema (as built by the ETL)**, last edited 2026-09-07 — authoritative for all table, column, measure and dimension facts. Supersedes the star-schema sketch in Project Description §3.2 [Notion-confirmed].
2. **This document's [User-directed] decisions** — supersede older Notion technology notes where explicitly recorded in §Assumptions and §Open Questions (LangGraph over LangChain, Python 3.13 over 3.11, no authentication in MVP).
3. **Project Description — Ground Truth Document**, last updated 2026-03-15 [Notion-confirmed].
4. **Epic 04 "Chatbot Cognitivo" backlog (US-4.1 … US-4.4)** [Notion-confirmed].
5. **CI/CD Pipelines — GitHub Actions, Python UV & AWS Lambda** [Notion-confirmed].
6. **Local repository state** [Repo-confirmed].

## Glossary

### Domain Terms

- **HSE / SST**: Health, Safety and Environment (English) / Seguridad y Salud en el Trabajo (Spanish). The occupational health and safety domain that bounds every supported question.
- **ABI (Augmented Business Intelligence)**: The Kognit AI HSE ecosystem model combining Descriptive (BI dashboards), Predictive (ML severity classification) and Cognitive (this chatbot) intelligence vectors
- **Incident**: An HSE event recorded in the warehouse with `dim_incident_type.category = 'Incident'`; one row in `fact_incidents` per `record_no` 
- **Near Miss**: An HSE event with `dim_incident_type.category = 'Near Miss'`.
- **Hazard**: An HSE event with `dim_incident_type.category = 'Hazard'`.
- **Severity**: `dim_incident_type.severity`, one of `minor`, `serious`, `fatal`, `unknown`, mapped from raw Intelex codes S0–S5 by the ETL (`S0`→minor, `S1`→minor, `S2`→serious, `S3a`→serious, `S3b`→serious, `S4`→fatal, `S5`→fatal, other/null→unknown)
- **Potential Severity**: `dim_incident_type.potential_severity`, the same mapping applied to the potential outcome of the event.
- **severity_index**: The weighted actual-severity measure on `fact_incidents` (Fatal=100, Serious=50, Minor=10, unknown=0)
- **incident_count**: The additive measure on `fact_incidents`, value `1` per incident row.
- **action_count**: The additive measure on `fact_actions`, value `1` per discrete corrective-action row and `0` for the zero-action sentinel row.
- **record_no**: The natural event key carried on `fact_incidents` and `fact_actions` as a **degenerate dimension**; the sole join key between incidents and their corrective actions.
- **Star schema**: The dimensional model in which fact tables (`fact_incidents`, `fact_actions`) reference conformed dimension tables through surrogate keys.
- **Surrogate key**: A warehouse-owned `sk_*` identity column that is the primary key of a dimension.
- **Business key**: The natural-source column set carrying a UNIQUE constraint on a dimension, used for idempotent ETL upsert.
- **Loaded data scope**: Only finalized Colombia / "The Americas" incidents are present in the warehouse; rows whose `Workflow.Status` is `H&S Verification` or `Line Manager Verification` are excluded by the ETL (other microservice not in this repo)`transform.filter_to_scope`.

### System Names (referenced by requirements)

- **LLM_API**: The whole microservice, deployed as the AWS Lambda function `kognit-ai-hse-llm-api` behind API Gateway.
- **Chat_Endpoint**: The HTTP interface component that accepts chat requests and returns chat responses.
- **Agent_Orchestrator**: The LangGraph state machine that executes the fixed node sequence for one chat turn.
- **Scope_Guard**: The component that renders the **HSE scope decision** before any warehouse access.
- **Intent_Classifier**: The component that classifies a message as `DATA_QUERY` or `GENERAL_CHAT` and extracts analytics intent.
- **Schema_Context_Provider**: The component that supplies the **approved schema allow-list** to the model.
- **SQL_Generator**: The component that produces a read-only query plan or SQL statement from the analytics intent.
- **Query_Firewall**: The non-LLM enforcement layer that validates generated SQL before execution.
- **Query_Executor**: The component that executes validated SQL against the warehouse using the `llm_read` role.
- **Answer_Synthesizer**: The component that converts a warehouse result set into a natural-language answer.
- **Conversation_Store**: The component that retains conversation turns keyed by `conversation_id`.
- **Model_Provider_Adapter**: The abstraction over the OpenAI-compatible model provider, designed for future AWS Bedrock compatibility.
- **Request_Logger**: The component that emits one log entry per request outcome.
- **Config_Loader**: The component that resolves environment-based configuration and secret references.

### Service Concepts

- **HSE scope decision**: The recorded verdict of `Scope_Guard` for one request, one of `IN_SCOPE`, `OUT_OF_SCOPE`, or `UNSAFE`.
- **Query firewall**: The deterministic, non-LLM validation of a SQL string that admits a statement only if it is a single `SELECT` over allow-listed identifiers with a mandatory row limit.
- **Approved schema allow-list**: The explicit, configuration-owned set of physical table names, view names, column names, dimension attributes and measures that `Schema_Context_Provider` exposes and `Query_Firewall` admits.
- **`llm_read`**: The read-only PostgreSQL role used for every warehouse query issued by `LLM_API`, holding `CONNECT`, `USAGE` and `SELECT` privileges only.
- **`conversation_id`**: The frontend-facing identifier that isolates one conversation's retained context from every other conversation.
- **DEMO user**: The single fixed user identity `DEMO` to which every MVP conversation belongs; the MVP has no authentication, user management, authorization or RBAC.
- **Chat turn**: One request/response cycle consisting of a single user message and the single assistant answer produced for it.
- **Row cap**: The maximum number of result rows the `Query_Executor` returns for one query.

## MVP Scope

### In Scope

1. A single chat endpoint that accepts one natural-language HSE analytics question plus a `conversation_id` and returns one natural-language answer.
2. HSE scope validation and rejection of out-of-scope or unsafe requests **before** any warehouse access.
3. Intent classification into `DATA_QUERY` and `GENERAL_CHAT`.
4. Text-to-SQL generation restricted to the approved schema allow-list.
5. A non-LLM query firewall enforcing single-statement, `SELECT`-only, allow-listed, row-limited SQL.
6. Read-only warehouse execution through the `llm_read` role.
7. Natural-language answer synthesis including the zero-result case.
8. In-memory conversation context keyed by `conversation_id`, with defined TTL and eviction.
9. One structured log entry per request describing the outcome.
10. A model-provider abstraction with a configurable model and no hard-coded provider.
11. Environment-based configuration resolved through UV-managed dependencies and SSM references.
12. Docker-based local execution instructions for the service.
13. Automated tests meeting the Definition of Done coverage threshold, executable without a live model provider or live warehouse.

### Out of Scope

1. **Authentication, authorization, user management and RBAC.** Every conversation belongs to the fixed `DEMO` user. This is a documented deviation from Project Description §10.2 — see §Risks R-3 and §Open Questions OQ-7.
2. **Persistent conversation storage.** History is held in application memory only; see §Risks R-5.
3. **Lost-workday analytics.** No lost-workday measure exists in the warehouse as built; see §Open Questions OQ-1.
4. **Employee-level or employee-dimension analytics.** No employee dimension exists in the authoritative schema; see §Open Questions OQ-2.
5. **Semantic / embedding search over free-text incident narrative** (`dim_text_event`), which the schema documents as "not for raw use in tabular models".
6. **Frequency-rate and any other metric not present in the authoritative schema.** The frequency-rate metric is intentionally excluded from `fact_incidents`.
7. **Write access of any kind** to the warehouse or to any other data store.
8. **Free-form SQL execution** on behalf of the user, including passthrough of user-supplied SQL.
9. **Medical, legal, HR-decision or financial advice** of any form.
10. **Structured centralized logging, distributed tracing, monitoring dashboards, query auditing and model observability**, which are recorded as future work in §Future Work.
11. **Streaming responses, multi-turn clarification loops beyond a single clarification prompt, file upload, and chart generation.**
12. **Changes to the ETL, the warehouse schema, the Statistics API or the ML API.**

## Requirements

### Requirement 1: Chat API Contract

**User Story:** As a frontend developer, I want a single documented chat endpoint with a stable request and response contract, so that I can integrate the `ChatInterface` component without depending on internal agent details.

Provenance: [Notion-confirmed: Project Description §4.4 documents `POST /chat/message`] reconciled with [User-directed] `conversation_id` and fixed `DEMO` user. See §Open Questions OQ-8.

#### Acceptance Criteria

1. THE Chat_Endpoint SHALL expose exactly one HTTP `POST` route at path `/chat/message` relative to the service root path `/llm`, so that the absolute route path is `/llm/chat/message`.
2. THE Chat_Endpoint SHALL accept a request body of media type `application/json` with character encoding UTF-8 containing a required non-null `message` field of type string and an optional `conversation_id` field of type string or JSON `null`, where a supplied `conversation_id` value consists of `1` to `64` characters drawn from ASCII letters, ASCII digits, hyphen and underscore.
3. WHEN a request body omits the `message` field or supplies `message` as JSON `null`, THE Chat_Endpoint SHALL reject the request with HTTP status `422` and a JSON body containing the `request_id` value and identifying `message` as the missing or null field.
4. WHEN a request body contains a `message` field whose length is `0` characters after Unicode NFC normalization and removal of leading and trailing whitespace, THE Chat_Endpoint SHALL reject the request with HTTP status `422` and a JSON body containing the `request_id` value and identifying `message` as invalid.
5. WHEN a request body contains a `message` field whose length after Unicode NFC normalization and removal of leading and trailing whitespace exceeds `2000` Unicode code points, THE Chat_Endpoint SHALL reject the request with HTTP status `422` and a JSON body containing the `request_id` value and stating the maximum supported message length of `2000` characters.
6. WHEN a request body omits the `conversation_id` field or supplies `conversation_id` as JSON `null`, THE Chat_Endpoint SHALL generate a `conversation_id` value formatted as a 36-character UUID version 4 string, use that value for the turn, and return it in the `conversation_id` field of the response body.
7. THE Chat_Endpoint SHALL set the responded `user_id` field to the literal value `DEMO` for every request.
8. WHEN a request body supplies a `user_id` field, THE Chat_Endpoint SHALL ignore the supplied value and respond with `user_id` set to `DEMO`.
9. WHEN a chat turn completes successfully, THE Chat_Endpoint SHALL respond with HTTP status `200`, response media type `application/json` with character encoding UTF-8, and a JSON body containing the non-null fields `response` (string of at least `1` character), `conversation_id` (string), `user_id` (string), `intent` (string), `request_id` (string) and `scope_decision` (string).
10. THE Chat_Endpoint SHALL restrict the responded `intent` field to one of the values `DATA_QUERY`, `GENERAL_CHAT`, `CLARIFICATION_NEEDED` or `REJECTED`, and SHALL respond with `intent` set to `REJECTED` only when the responded `scope_decision` value is `OUT_OF_SCOPE` or `UNSAFE`.
11. THE Chat_Endpoint SHALL restrict the responded `scope_decision` field to one of the values `IN_SCOPE`, `OUT_OF_SCOPE` or `UNSAFE`, and SHALL populate that field in every response body returned with HTTP status `200`.
12. WHERE the configuration flag `expose_executed_sql` is enabled, WHEN a turn executed a warehouse query, THE Chat_Endpoint SHALL include a `query_executed` field containing the executed SQL statement in the response body.
13. WHERE the configuration flag `expose_executed_sql` is disabled, or WHERE the flag is enabled and the turn executed no warehouse query, THE Chat_Endpoint SHALL omit the `query_executed` field from the response body.
14. THE Config_Loader SHALL default the `expose_executed_sql` flag to disabled.
15. THE Chat_Endpoint SHALL validate every request body and serialize every response body through Pydantic models, SHALL ignore request body fields that the request model does not declare including a client-supplied `request_id` field, SHALL generate the `request_id` value for every request as a 36-character UUID version 4 string returned in every response body it produces, and SHALL pass the NFC-normalized, whitespace-trimmed `message` value to THE Agent_Orchestrator.
16. THE Chat_Endpoint SHALL publish an OpenAPI schema describing the request body, the response body and the HTTP status codes `200`, `400`, `415`, `422`, `503` and `504`.
17. THE Chat_Endpoint SHALL accept requests that carry an HTTP `Authorization` header and process them identically to requests without that header, so that Bearer Token authentication can be introduced without changing the request or response contract.
18. THE LLM_API SHALL retain the existing `GET /health` route behaviour, reporting warehouse connectivity status.
19. WHEN the `GET /health` route is called, THE LLM_API SHALL respond with HTTP status `200` and a body reporting a status value for warehouse connectivity and a status value for model-provider configuration availability.
20. IF a request body is not well-formed JSON, THEN THE Chat_Endpoint SHALL reject the request with HTTP status `400` and a JSON body containing the `request_id` value and stating that the request body is not valid JSON, and SHALL NOT invoke THE Agent_Orchestrator.
21. IF a request carries a `Content-Type` header whose media type is not `application/json`, THEN THE Chat_Endpoint SHALL reject the request with HTTP status `415` and a JSON body containing the `request_id` value and stating that `application/json` is the supported media type.
22. IF a request body supplies a `conversation_id` value that violates the format constraints of acceptance criterion 2, THEN THE Chat_Endpoint SHALL reject the request with HTTP status `422` and a JSON body containing the `request_id` value and identifying `conversation_id` as invalid, and THE Conversation_Store SHALL create no conversation record for the rejected value.

### Requirement 2: HSE Scope Validation and Out-of-Scope Rejection

**User Story:** As a Security Architect, I want every request classified for HSE scope before any data access occurs, so that unrelated, sensitive or hostile requests never reach the warehouse.

Provenance: [Notion-confirmed: US-4.1 third acceptance criterion — out-of-scope requests are rejected with a message to the user] extended per [User-directed] rejection categories. Extension beyond backlog: the pre-warehouse ordering guarantee and the credential-exfiltration category are [New proposed requirement].

#### Acceptance Criteria

1. WHILE the HSE scope decision recorded for a turn is absent or holds a value other than `IN_SCOPE`, THE Query_Executor SHALL open no warehouse connection and SHALL send no statement to the warehouse for that turn.
2. IF THE Scope_Guard produces the decision `OUT_OF_SCOPE`, THEN THE Agent_Orchestrator SHALL terminate the turn without invoking THE SQL_Generator, without opening a warehouse connection, and with at most `1` model-provider call issued for that turn in total.
3. IF THE Scope_Guard produces the decision `UNSAFE`, THEN THE Agent_Orchestrator SHALL terminate the turn without invoking THE SQL_Generator, without opening a warehouse connection, and with at most `1` model-provider call issued for that turn in total.
4. WHEN a message requests sales, revenue, finance, marketing, purchasing, inventory or other non-HSE operational information, THE Scope_Guard SHALL produce the decision `OUT_OF_SCOPE`.
5. WHEN a message requests general human-resources information unrelated to HSE incident analysis, THE Scope_Guard SHALL produce the decision `OUT_OF_SCOPE`.
6. WHEN a message requests medical diagnosis or medical treatment advice, THE Scope_Guard SHALL produce the decision `OUT_OF_SCOPE`.
7. WHEN a message requests a legal conclusion, a liability assessment or an employment decision, THE Scope_Guard SHALL produce the decision `OUT_OF_SCOPE`.
8. WHEN a message requests credentials, access tokens, code execution, API keys, database connection strings, hidden prompts, system prompts or internal instructions, THE Scope_Guard SHALL produce the decision `UNSAFE`.
9. WHEN a message requests that data be altered, deleted, inserted, updated or otherwise modified, THE Scope_Guard SHALL produce the decision `UNSAFE`.
10. WHEN a message supplies a SQL statement, supplies a SQL fragment, or requests execution of a database statement other than a Health and Safety analytics question expressed in natural language, THE Scope_Guard SHALL produce the decision `UNSAFE`.
11. WHEN THE Scope_Guard produces the decision `OUT_OF_SCOPE`, THE Chat_Endpoint SHALL respond with HTTP status `200`, `intent` set to `REJECTED`, `scope_decision` set to `OUT_OF_SCOPE`, and a `response` value stating that the assistant supports approved Health and Safety analytics questions only, expressed in Spanish when the user message is in Spanish and in English for every other message language, unless THE Config_Loader resolves `answer_language` to a fixed language code.
12. WHEN THE Scope_Guard produces the decision `UNSAFE`, THE Chat_Endpoint SHALL respond with HTTP status `200`, `intent` set to `REJECTED`, `scope_decision` set to `UNSAFE`, and a `response` value stating that the assistant supports approved Health and Safety analytics questions only, expressed in Spanish when the user message is in Spanish and in English for every other message language, unless THE Config_Loader resolves `answer_language` to a fixed language code.
13. WHEN THE Scope_Guard produces a rejection decision, THE Chat_Endpoint SHALL respond with a `response` value of at most `300` characters that excludes schema names, table names, column names, measure names, configuration values, credential values, system prompt text, the matched rejection category and the reasoning of the model-assisted classification.
14. WHEN a message contains an instruction directing THE Agent_Orchestrator or the model provider to disregard, override, replace or disclose its configured constraints, instructions or role, THE Scope_Guard SHALL produce the decision `UNSAFE`.
15. THE Scope_Guard SHALL record the produced HSE scope decision in the conversation turn record and in the request log entry before THE Agent_Orchestrator transitions from the scope validation node to any subsequent node.
16. THE Scope_Guard SHALL produce every HSE scope decision by evaluating a deterministic rule stage that issues no model-provider call, followed, only where the deterministic stage matches no rejection category of criteria 4 to 10 and criterion 14, by exactly one model-assisted classification call.
17. IF the model-assisted classification call returns no verdict, returns a verdict that fails Pydantic validation, or returns a verdict outside the set `IN_SCOPE`, `OUT_OF_SCOPE` and `UNSAFE`, THEN THE Scope_Guard SHALL produce the decision `OUT_OF_SCOPE` without issuing a further model-provider call for that turn.
18. THE Scope_Guard SHALL produce the decision `UNSAFE` for a message matching any category of criteria 8 to 10 or criterion 14 irrespective of any additional Health and Safety analytics content in the same message, the decision `OUT_OF_SCOPE` for a message matching any category of criteria 4 to 7 and no category of criteria 8 to 10 and criterion 14 irrespective of any additional Health and Safety analytics content in the same message, and the decision `IN_SCOPE` for every other message, including greetings, courtesy expressions and messages of one word, and irrespective of the natural language of the message.

### Requirement 3: Intent Classification and Analytics Intent Understanding

**User Story:** As a Developer, I want the system to analyze the user message to decide whether it needs to look up data in the warehouse or is a general query, so that the execution flow is efficient.

Provenance: [Notion-confirmed: US-4.1 "Orquestador de Intención (Semantic Analysis)", 5 pts, Sprint 9].

#### Acceptance Criteria

1. WHILE THE Scope_Guard decision for a turn is `IN_SCOPE`, THE Intent_Classifier SHALL classify the message as exactly one of `DATA_QUERY`, `GENERAL_CHAT` or `CLARIFICATION_NEEDED`.
2. WHEN THE Intent_Classifier classifies a message as `DATA_QUERY`, THE Agent_Orchestrator SHALL proceed to schema-context selection and query generation.
3. WHEN THE Intent_Classifier classifies a message as `GENERAL_CHAT`, THE Agent_Orchestrator SHALL produce an answer without executing a warehouse query.
4. WHEN THE Intent_Classifier classifies a message as `CLARIFICATION_NEEDED`, THE Chat_Endpoint SHALL respond with HTTP status `200`, `intent` set to `CLARIFICATION_NEEDED`, and a `response` value that names the missing or ambiguous element of the question and that excludes table names and column names.
5. WHEN THE Intent_Classifier classifies a message as `DATA_QUERY`, THE Intent_Classifier SHALL emit a structured analytics intent containing exactly the fields `measure`, `time_range`, `grouping_attributes`, `filters`, `ordering`, `limit` and `confidence`, of which `measure`, `time_range`, `limit` and `confidence` are mandatory and `grouping_attributes`, `filters` and `ordering` are optional.
6. THE Intent_Classifier SHALL emit the structured analytics intent as a Pydantic-validated object.
7. IF the model provider returns an analytics intent that fails Pydantic validation, THEN THE Agent_Orchestrator SHALL terminate the turn and THE Chat_Endpoint SHALL respond with a `response` value stating that the question could not be interpreted.
8. WHEN a message contains a relative date expression, THE Intent_Classifier SHALL resolve the expression to an absolute start date and an absolute end date using the configured reference timezone.
9. THE Config_Loader SHALL expose the reference timezone as configuration with the default value `America/Bogota`.
10. WHEN THE Intent_Classifier resolves a relative month expression, THE Intent_Classifier SHALL produce a start date equal to the first calendar day of the target month and an end date equal to the last calendar day of the target month, with both boundaries treated as inclusive.
11. THE Intent_Classifier SHALL resolve relative date expressions against the request timestamp of the current turn.
12. WHEN THE Intent_Classifier classifies a message as `CLARIFICATION_NEEDED`, THE Agent_Orchestrator SHALL terminate the turn without generating SQL and without executing a warehouse query.
13. THE Intent_Classifier SHALL set the `measure` field of a structured analytics intent to exactly one of the values `incident_count`, `severity_index` or `action_count`.
14. WHEN a message requests a count of incidents, near misses or hazards without naming a measure, THE Intent_Classifier SHALL set the `measure` field to `incident_count`.
15. THE Intent_Classifier SHALL populate the `grouping_attributes` field with between `0` and `3` entries, each entry being a dimension attribute present in the approved schema allow-list of Requirement 4, and SHALL default the field to an empty list when the message requests no breakdown.
16. WHEN a message requests a week-level breakdown, THE Intent_Classifier SHALL record the grouping as a derived week grouping over `dim_date.date`, because the warehouse contains no week column.
17. THE Intent_Classifier SHALL populate the `filters` field with between `0` and `5` entries, each entry containing one dimension attribute present in the approved schema allow-list of Requirement 4, one operator from the set `equals`, `not_equals`, `in`, `greater_than`, `less_than`, `between`, and at most `20` literal comparison values, and SHALL default the field to an empty list when the message states no filter.
18. WHEN a message requests a ranking of results, THE Intent_Classifier SHALL populate the `ordering` field with one field name drawn from the emitted `measure` or the emitted `grouping_attributes` and one direction value of either `ASC` or `DESC`.
19. WHEN a message states an explicit result count `N`, THE Intent_Classifier SHALL set the `limit` field to `N` bounded to the range `1` to the configured row cap of Requirement 6, and WHEN a message states no explicit result count, THE Intent_Classifier SHALL set the `limit` field to the configured row cap.
20. IF a message requests more than `3` grouping attributes or more than `5` filters, THEN THE Intent_Classifier SHALL classify the message as `CLARIFICATION_NEEDED` and the clarification prompt SHALL state the maximum supported number of breakdowns and filters.
21. THE Intent_Classifier SHALL populate the `confidence` field with a decimal value between `0.00` and `1.00` inclusive, expressed to two decimal places.
22. IF the emitted `confidence` value is below the configured intent confidence threshold, THEN THE Intent_Classifier SHALL classify the message as `CLARIFICATION_NEEDED` and the clarification prompt SHALL restate the interpretation the classifier reached.
23. WHILE the emitted `confidence` value is greater than or equal to the configured intent confidence threshold and every mandatory intent field is populated, THE Intent_Classifier SHALL classify the message as `DATA_QUERY` without requesting clarification, irrespective of whether the optional fields are empty.
24. THE Config_Loader SHALL expose the intent confidence threshold as configuration with a default value of `0.60`.
25. WHILE THE Conversation_Store supplies a non-empty context for the turn, WHEN a message omits the measure, the time range, the grouping attributes or the filters and refers to a previous turn through a pronoun or an elliptical phrase, THE Intent_Classifier SHALL populate the omitted fields from the most recent `DATA_QUERY` analytics intent retained for that `conversation_id`.
26. WHEN THE Intent_Classifier populates omitted fields from the retained context, THE Intent_Classifier SHALL overwrite each retained field that the current message restates and SHALL retain every field that the current message does not restate.
27. THE Intent_Classifier SHALL emit every structured analytics intent as self-contained, with the `measure`, `time_range` and `limit` fields populated by absolute values that carry no reference to a previous turn.
28. IF a message omits the measure or the time range and THE Conversation_Store supplies no retained `DATA_QUERY` analytics intent for that `conversation_id`, THEN THE Intent_Classifier SHALL classify the message as `CLARIFICATION_NEEDED` and the clarification prompt SHALL name the missing measure or missing period.
29. THE Intent_Classifier SHALL resolve the date expressions `today`, `yesterday`, `this week`, `last week`, `this month`, `last month`, `this quarter`, `last quarter`, `this year`, `last year`, `last N days`, a named calendar month with or without a year, and an explicit two-date range, into an inclusive start date and an inclusive end date, and SHALL classify a message whose date expression falls outside this set as `CLARIFICATION_NEEDED`.
30. WHEN a message contains the expression `today`, THE Intent_Classifier SHALL set both the start date and the end date to the request date in the configured reference timezone, and WHEN a message contains the expression `yesterday`, THE Intent_Classifier SHALL set both the start date and the end date to the calendar day preceding the request date in the configured reference timezone.
31. WHEN a message contains the expression `this week`, THE Intent_Classifier SHALL set the start date to the configured first day of the week of the week containing the request date and the end date to the sixth calendar day after that start date, and WHEN a message contains the expression `last week`, THE Intent_Classifier SHALL set the start date to the configured first day of the week of the preceding week and the end date to the sixth calendar day after that start date.
32. THE Config_Loader SHALL expose the first day of the week as configuration with the default value `MONDAY`.
33. WHEN a message contains the expression `this quarter`, THE Intent_Classifier SHALL set the start date to the first calendar day and the end date to the last calendar day of the calendar quarter containing the request date, and WHEN a message contains the expression `last quarter`, THE Intent_Classifier SHALL set those boundaries to the first and last calendar day of the preceding calendar quarter.
34. WHEN a message contains the expression `this year`, THE Intent_Classifier SHALL set the start date to `01 January` and the end date to `31 December` of the calendar year containing the request date, and WHEN a message contains the expression `last year`, THE Intent_Classifier SHALL set those boundaries to `01 January` and `31 December` of the preceding calendar year.
35. WHEN a message requests the last `N` days, THE Intent_Classifier SHALL set the end date to the request date in the configured reference timezone and the start date to the request date minus `N` minus `1` calendar days, for values of `N` from `1` to `365` inclusive.
36. IF a message requests a rolling window longer than `365` days, THEN THE Intent_Classifier SHALL classify the message as `CLARIFICATION_NEEDED` and the clarification prompt SHALL state the maximum supported window of `365` days.
37. WHEN a message names a calendar month together with a year, THE Intent_Classifier SHALL resolve the time range to that month of that year, and WHEN a message names a calendar month without a year, THE Intent_Classifier SHALL resolve the time range to the most recent occurrence of that month whose last calendar day is on or before the request date.
38. WHEN a message states an explicit two-date range, THE Intent_Classifier SHALL set the start date to the earlier stated date and the end date to the later stated date, with both boundaries inclusive.
39. IF a message states an explicit two-date range whose stated start date is later than its stated end date and the intended order cannot be determined from the message text, THEN THE Intent_Classifier SHALL classify the message as `CLARIFICATION_NEEDED` and the clarification prompt SHALL restate both stated dates.
40. IF a message states two or more time ranges that are not identical after resolution, THEN THE Intent_Classifier SHALL classify the message as `CLARIFICATION_NEEDED` and the clarification prompt SHALL restate each resolved period and SHALL ask which period applies.
41. IF a resolved time range has a start date later than the request date in the configured reference timezone, THEN THE Agent_Orchestrator SHALL terminate the turn without executing a warehouse query and THE Chat_Endpoint SHALL respond with a `response` value stating that the requested period lies in the future and that no records exist for it.
42. IF a resolved time range has a start date on or before the request date and an end date later than the request date in the configured reference timezone, THEN THE Intent_Classifier SHALL set the end date to the request date in the configured reference timezone.
43. IF a resolved time range contains no `date` value present in `dim_date`, THEN THE Agent_Orchestrator SHALL terminate the turn without executing an analytics query and THE Chat_Endpoint SHALL respond with a `response` value stating that the requested period lies outside the loaded data coverage.
44. WHEN a message classified as `DATA_QUERY` states no date expression and THE Conversation_Store supplies no retained time range for that `conversation_id`, THE Intent_Classifier SHALL set the end date to the request date in the configured reference timezone and the start date to the request date minus the configured default lookback window.
45. THE Config_Loader SHALL expose the default lookback window as configuration with a default value of `365` days.

### Requirement 4: Approved Schema Context

**User Story:** As a Developer, I want the model to receive only an explicitly approved subset of the warehouse schema, so that generated queries stay within known-safe structures and token cost stays bounded.

Provenance: [Notion-confirmed: US-4.2 — "The LLM prompt must include the database schema (relevant tables and columns)" and the documented HIGH RISK of exceeding token limits]. The allow-list as an independently enforced artifact is [New proposed requirement].

#### Acceptance Criteria

1. THE Schema_Context_Provider SHALL maintain the approved schema allow-list as a single artifact that enumerates, for each allow-listed table, the table name, the allow-listed column names of that table and the allow-listed measure names of that table.
2. THE Schema_Context_Provider SHALL express every table and column name in the allow-list in lowercase, matching the physical unquoted identifiers created by the ETL.
3. THE Schema_Context_Provider SHALL include the fact tables `fact_incidents` and `fact_actions` in the allow-list.
4. THE Schema_Context_Provider SHALL include the dimension tables `dim_date`, `dim_location`, `dim_incident_type`, `dim_shift`, `dim_cause`, `dim_status`, `dim_action_details`, `dim_equipment`, `dim_ppe`, `dim_injury`, `dim_high_risk_area` in the allow-list.
5. THE Schema_Context_Provider SHALL include the bridge tables `bridge_incident_ppe` and `bridge_incident_injury` in the allow-list.
6. THE Schema_Context_Provider SHALL exclude the table `dim_text_event` and all of its columns from the allow-list.
7. THE Schema_Context_Provider SHALL include the measures `incident_count`, `severity_index` and `action_count` in the allow-list.
8. WHEN THE Schema_Context_Provider supplies schema context for a turn, THE Schema_Context_Provider SHALL include only the allow-listed tables and columns that the structured analytics intent references together with the allow-listed tables and columns required by the join keys connecting them, and SHALL exclude every other allow-listed table and column.
9. THE Schema_Context_Provider SHALL limit the schema context supplied for one turn to a configured maximum token budget, counted with the tokenizer of the configured model identifier.
10. THE Config_Loader SHALL expose the schema-context token budget as configuration with a default value of `4000` tokens.
11. WHEN THE Schema_Context_Provider supplies schema context, THE Schema_Context_Provider SHALL include the documented join keys, namely the `sk_*` surrogate-key relationships between `fact_incidents` and its dimensions, the `sk_*` relationships between `fact_actions` and `dim_action_details`, `dim_date` and `dim_location`, and the `record_no` degenerate-dimension join between `fact_incidents`, `fact_actions`, `bridge_incident_ppe` and `bridge_incident_injury`.
12. THE Schema_Context_Provider SHALL supply at least `3` and at most `10` example question and SQL pairs to the model provider as few-shot prompt content, each pair referencing only identifiers present in the approved schema allow-list and each example SQL statement satisfying every rule of Requirement 6.
13. THE Schema_Context_Provider SHALL source the approved schema allow-list from a single configuration artifact carrying a version identifier, and THE Query_Firewall SHALL read the same artifact and the same version identifier for its allow-list verdicts.
14. WHEN THE LLM_API initializes an execution environment, THE Schema_Context_Provider SHALL verify every allow-listed table entry and every allow-listed column entry against the configured approved schema through a read-only query issued by THE Query_Executor, and SHALL record each entry as `verified` or `absent`.
15. IF an allow-list entry is recorded as `absent`, THEN THE Schema_Context_Provider SHALL exclude that entry from every schema context supplied to the model provider and from every example question and SQL pair.
16. IF an allow-list entry is recorded as `absent`, THEN THE Query_Firewall SHALL reject every SQL statement that references that entry.
17. IF at least one allow-list entry is recorded as `absent`, THEN THE LLM_API SHALL report a degraded schema-verification status on the `GET /health` route stating the count of absent table entries and the count of absent column entries.
18. IF the allow-list verification query does not complete, THEN THE Schema_Context_Provider SHALL record every allow-list entry as `unverified`, SHALL supply schema context from the artifact-declared entries, THE Query_Firewall SHALL enforce the artifact-declared allow-list unchanged, and THE LLM_API SHALL report an unverified schema-verification status on the `GET /health` route.
19. THE Schema_Context_Provider SHALL scope every allow-listed column entry to exactly one allow-listed table entry, so that a column name allow-listed for one table is absent from the allow-list of every other table.
20. IF a SQL statement references a column identifier qualified by a table name or a table alias, THEN THE Query_Firewall SHALL admit that identifier only if the column entry is allow-listed for the qualifying table.
21. IF a SQL statement references an unqualified column identifier that is allow-listed for more than one of the tables named in the statement, THEN THE Query_Firewall SHALL reject the statement.
22. IF a SQL statement references an unqualified column identifier that is allow-listed for exactly one of the tables named in the statement, THEN THE Query_Firewall SHALL admit that identifier as belonging to that table.
23. WHEN THE Schema_Context_Provider supplies schema context, THE Schema_Context_Provider SHALL include exactly the selected table names, the allow-listed column names of each selected table, the declared data type of each included column, the allow-listed measure names of each included fact table, and the join keys of criterion 11.
24. THE Schema_Context_Provider SHALL exclude table row counts, column cardinality statistics, sample data rows, index definitions, constraint definitions and free-text column values from every schema context supplied to the model provider.
25. WHERE the configuration flag `include_dimension_values` is enabled, THE Schema_Context_Provider SHALL include the distinct stored values of the allow-listed attributes `dim_incident_type.category`, `dim_incident_type.severity`, `dim_incident_type.potential_severity`, `dim_status.status`, `dim_shift.shift_name`, `dim_cause.criticality_level`, `dim_ppe.ppe_type` and `dim_location.plant` in the schema context for every one of those attributes whose table is selected for the turn.
26. THE Schema_Context_Provider SHALL source every enumerated dimension value from the warehouse through a read-only query issued by THE Query_Executor, and SHALL exclude enumerated values supplied by the model provider and enumerated values held in source code.
27. IF an enumerated attribute holds more than the configured per-attribute enumerated-value maximum of distinct stored values, THEN THE Schema_Context_Provider SHALL exclude the values of that attribute from the schema context and SHALL state in the schema context that the value set of that attribute is not enumerated.
28. THE Config_Loader SHALL default the `include_dimension_values` flag to enabled and SHALL expose the per-attribute enumerated-value maximum as configuration with a default value of `50` values.
29. IF the schema context selected for a turn exceeds the configured token budget, THEN THE Schema_Context_Provider SHALL reduce the context by applying the following steps in this order and SHALL stop at the first step after which the context is within the budget: first remove all enumerated dimension values, second reduce the example question and SQL pairs to `1` pair, third remove every column of the selected tables that the structured analytics intent does not reference and that no included join key requires.
30. IF the schema context exceeds the configured token budget after every reduction step of criterion 29 has been applied, THEN THE Schema_Context_Provider SHALL supply no schema context for that turn and THE LLM_API SHALL respond with a `response` value stating that the question could not be answered.
31. WHEN THE Schema_Context_Provider computes the schema context for a turn, THE Schema_Context_Provider SHALL cache the computed context in the execution environment keyed by the allow-list artifact version identifier, the selected table and column set, the configured token budget and the configured model identifier.
32. IF the allow-list artifact version identifier, the configured token budget, the configured model identifier or the `include_dimension_values` flag differs from the value held in a cache key, THEN THE Schema_Context_Provider SHALL discard every cached schema context and every cached enumerated dimension value.
33. THE Schema_Context_Provider SHALL discard a cached schema context and a cached enumerated dimension value set whose age exceeds the configured schema cache time-to-live, and THE Config_Loader SHALL expose that time-to-live as configuration with a default value of `3600` seconds.
34. THE Schema_Context_Provider SHALL exclude every column of `dim_text_event` and the column `fact_incidents.sk_text_event` from the approved schema allow-list, from every schema context supplied to the model provider and from every example question and SQL pair.

### Requirement 5: Read-Only Query Generation

**User Story:** As a Manager or Coordinator, I want to ask HSE related questions like "how many accidents were there in plant A" and have the system translate the question or questiones into a warehouse query, so that I get the real figure without knowing how to program.

Provenance: [Notion-confirmed: US-4.2 "Generación de SQL con IA (Text-to-SQL)", 13 pts, Sprint 9].

#### Acceptance Criteria

1. WHEN THE Intent_Classifier emits a structured analytics intent, THE SQL_Generator SHALL produce exactly one SQL statement for that intent.
2. THE SQL_Generator SHALL produce SQL statements whose first keyword token is `SELECT` or `WITH`.
3. THE SQL_Generator SHALL produce SQL statements that parse without error against the PostgreSQL 16 grammar.
4. THE SQL_Generator SHALL produce SQL statements that reference only table identifiers, column identifiers and measure names present in the approved schema allow-list.
5. THE SQL_Generator SHALL include in every produced SQL statement a `LIMIT` clause specifying an integer value from `1` to the configured row cap inclusive.
6. THE SQL_Generator SHALL emit the produced SQL statement as a Pydantic-validated structured output containing the statement text, the referenced table identifiers, the referenced column identifiers and the ordered list of bound parameter values.
7. IF THE Query_Firewall rejects the produced SQL statement, THEN THE SQL_Generator SHALL attempt regeneration exactly one additional time for the same turn.
8. IF THE Query_Firewall rejects the regenerated SQL statement, THEN THE Agent_Orchestrator SHALL terminate the turn and THE Chat_Endpoint SHALL respond with a `response` value stating that the question could not be answered safely.
9. WHEN a structured analytics intent requests a week-level grouping, THE SQL_Generator SHALL derive the week from `dim_date.date` using `EXTRACT(WEEK FROM dim_date.date)` or `date_trunc('week', dim_date.date)`, because `dim_date` carries no week column.
10. WHEN a structured analytics intent requests a plant or location filter, THE SQL_Generator SHALL filter on `dim_location.plant` or `dim_location.area_on_site`.
11. WHEN a structured analytics intent requests a per-event corrective-action total, THE SQL_Generator SHALL aggregate `SUM(fact_actions.action_count)` grouped by `fact_actions.record_no` and SHALL retain the zero-action sentinel rows, so that an event with no corrective action reports a total of `0`.
12. THE SQL_Generator SHALL express every incident, near-miss and hazard volume measure as `SUM(fact_incidents.incident_count)` and SHALL exclude `COUNT(*)` from volume expressions over `fact_incidents`.
13. THE SQL_Generator SHALL express every weighted actual-severity measure as `SUM(fact_incidents.severity_index)`.
14. WHERE a produced SQL statement joins `fact_incidents` to `bridge_incident_ppe` or to `bridge_incident_injury`, THE SQL_Generator SHALL express the event volume measure as `COUNT(DISTINCT fact_incidents.record_no)`, or SHALL pre-aggregate the bridge table to exactly one row per `record_no` in a `WITH` subquery before the join.
15. WHERE a produced SQL statement joins `fact_incidents` to `bridge_incident_ppe` or to `bridge_incident_injury`, THE SQL_Generator SHALL exclude `SUM(fact_incidents.incident_count)` from the query block that performs that join, because the bridge grain of one row per `record_no` and `sk_ppe` or per `record_no` and `sk_injury` multiplies incident rows.
16. WHERE a produced SQL statement reports an incident measure and an action measure in the same result set, THE SQL_Generator SHALL pre-aggregate `fact_incidents` to one row per `record_no` and `fact_actions` to one row per `record_no` in separate `WITH` subqueries and SHALL join those subqueries on `record_no`, because the `fact_actions` grain of one row per `record_no` and `sk_action` inflates incident measures.
17. WHEN a structured analytics intent requests the number of events having at least one corrective action, THE SQL_Generator SHALL express the measure as `COUNT(DISTINCT fact_actions.record_no)` restricted to `fact_actions` rows whose `action_count` is greater than `0`.
18. WHEN a structured analytics intent requests a listing or a breakdown of the corrective actions taken, THE SQL_Generator SHALL restrict the statement to `fact_actions` rows whose `action_count` is greater than `0`, so that the zero-action sentinel row of `dim_action_details` is excluded from the listing.
19. WHERE a produced SQL statement can return more than one row, THE SQL_Generator SHALL include an `ORDER BY` clause whose key list produces a distinct ordering key for every returned row, so that repeated execution returns rows in the same order.
20. THE SQL_Generator SHALL include every selected non-aggregated column of a produced SQL statement in the `GROUP BY` clause of that statement.
21. WHEN a structured analytics intent carries a resolved start date and end date, THE SQL_Generator SHALL join the fact table to `dim_date` on `sk_date` and SHALL filter `dim_date.date` to the range from the resolved start date to the resolved end date with both boundaries inclusive.
22. WHEN a structured analytics intent filters on an event category, THE SQL_Generator SHALL filter `dim_incident_type.category` to exactly one of the values `Incident`, `Near Miss` or `Hazard`.
23. WHEN a structured analytics intent supplies a dimension text value taken from the user message, THE SQL_Generator SHALL compare that value against the stored column value after converting both sides to lowercase and removing diacritic marks.
24. THE SQL_Generator SHALL represent every user-supplied literal filter value in a produced SQL statement as a bound parameter placeholder and SHALL exclude that literal value from the statement text.
25. THE SQL_Generator SHALL exclude user-supplied text from the table identifier positions, the column identifier positions and the SQL keyword positions of every produced SQL statement.
26. THE SQL_Generator SHALL exclude the identifiers `dim_text_event` and `fact_incidents.sk_text_event` from every produced SQL statement.
27. WHEN a produced SQL statement groups on `dim_date.is_holiday`, THE SQL_Generator SHALL retain rows whose `dim_date.is_holiday` is NULL and SHALL place those rows in a grouping value distinct from the true grouping value and the false grouping value.
28. WHEN a produced SQL statement groups on `dim_incident_type.severity` or `dim_incident_type.potential_severity`, THE SQL_Generator SHALL retain rows whose value is `unknown` as a reported grouping value.
29. WHEN a produced SQL statement groups on `dim_injury.injury_type` or on `dim_injury.body_part`, THE SQL_Generator SHALL retain rows whose `injury_type` is `Unknown` and rows whose `body_part` is `No Body Part` as reported grouping values.
30. WHEN a structured analytics intent restricts analytics to events involving equipment, THE SQL_Generator SHALL filter `dim_equipment.is_equipment_involved` to true.
31. WHEN a structured analytics intent groups on an equipment attribute without restricting analytics to events involving equipment, THE SQL_Generator SHALL retain rows whose `dim_equipment.is_equipment_involved` is false.
32. IF THE Query_Firewall rejects a produced SQL statement, THEN THE SQL_Generator SHALL receive the machine-readable rejection reason category of Requirement 6 as the sole regeneration feedback and SHALL receive no free-text firewall diagnostic.
33. IF THE Query_Firewall rejects a produced SQL statement, THEN THE Chat_Endpoint SHALL exclude the rejected statement text and the rejection reason category from the `response` field.
34. THE SQL_Generator SHALL submit at most `2` SQL statements per chat turn to THE Query_Firewall.
35. THE SQL_Generator SHALL produce SQL statement text of at most `4000` characters.

### Requirement 6: Query Firewall (Non-LLM Enforcement)

**User Story:** As a Security Architect, I want to intercept the AI-generated SQL before it is executed, so that deletion or modification attempts are blocked even when the model is manipulated.

Provenance: [Notion-confirmed: US-4.3 "Firewall de Consultas (Security Layer)", 5 pts, Sprint 10, and Project Description §4.5 LLM Query Guard Rules]. The allow-list, statement-count, mandatory-limit and timeout controls extend the documented rules and are [New proposed requirement].

#### Acceptance Criteria

1. WHEN THE SQL_Generator produces a SQL statement, THE Query_Firewall SHALL validate the statement and produce a verdict of `ADMIT` or `REJECT` before THE Query_Executor sends the statement to the warehouse.
2. THE Query_Firewall SHALL reach its verdict from the statement text, the approved schema allow-list, the approved function allow-list and the configured numeric bounds only, without any call to the model provider and without any network call.
3. THE Query_Firewall SHALL admit a SQL statement only if the first keyword token of the statement is `SELECT` or `WITH`.
4. WHERE the first keyword token of a SQL statement is `WITH`, THE Query_Firewall SHALL admit the statement only if the body of every common table expression of the statement is a `SELECT` statement.
5. THE Query_Firewall SHALL admit a SQL statement only if tokenization yields exactly one top-level statement.
6. IF a SQL statement contains a statement-separator token at any position, including a separator followed only by whitespace, THEN THE Query_Firewall SHALL reject the statement.
7. IF a SQL statement contains any of the keywords `DROP`, `DELETE`, `UPDATE`, `INSERT`, `TRUNCATE`, `ALTER`, `CREATE`, `GRANT`, `REVOKE`, `COPY`, `MERGE`, `REPLACE`, `VACUUM`, `CALL`, `DO`, `EXECUTE`, `SET`, `RESET`, `LOCK`, `COMMENT`, `REINDEX`, `REFRESH`, `NOTIFY`, `LISTEN`, `PREPARE`, `DECLARE`, `FETCH`, `MOVE`, `CLOSE`, `SECURITY`, `ROLE`, `USER`, `DATABASE`, `SCHEMA`, `TABLESPACE`, `EXTENSION` or `FUNCTION` as a SQL keyword token, THEN THE Query_Firewall SHALL reject the statement.
8. IF a SQL statement contains a single-line comment token or a block comment token, THEN THE Query_Firewall SHALL reject the statement.
9. IF a SQL statement references a schema name other than the configured approved schema, THEN THE Query_Firewall SHALL reject the statement.
10. IF a SQL statement references a table identifier that is absent from the approved schema allow-list, THEN THE Query_Firewall SHALL reject the statement.
11. IF a SQL statement references a column identifier that is absent from the approved schema allow-list, THEN THE Query_Firewall SHALL reject the statement.
12. IF a SQL statement omits a `LIMIT` clause, THEN THE Query_Firewall SHALL reject the statement.
13. IF a SQL statement specifies a `LIMIT` value greater than the configured row cap, THEN THE Query_Firewall SHALL reject the statement.
14. THE Config_Loader SHALL expose the row cap as configuration with a default value of `1000` rows.
15. IF a SQL statement contains a function call whose function name is absent from the approved function allow-list, THEN THE Query_Firewall SHALL reject the statement.
16. WHEN THE Query_Firewall rejects a SQL statement, THE Query_Firewall SHALL record exactly one rejection reason code for that statement in the request log entry.
17. WHEN THE Query_Firewall rejects a SQL statement, THE Chat_Endpoint SHALL respond with a `response` value that excludes the rejected SQL statement text, the rejected identifiers and the rejection reason code.
18. THE Query_Firewall SHALL apply identical verdict rules to SQL statements irrespective of the origin of the statement text.
19. THE Query_Firewall SHALL operate deny-by-default, admitting a SQL statement only when every admission rule of this requirement evaluates to true and rejecting the statement in every other case.
20. IF THE Query_Firewall cannot tokenize a SQL statement, cannot parse it into a single query tree, or encounters a syntactic construct that its rule set does not classify, THEN THE Query_Firewall SHALL reject the statement.
21. THE Query_Firewall SHALL evaluate every keyword, identifier, schema, function and clause rule of this requirement against tokens produced by a PostgreSQL-dialect tokenizer that classifies each token as a keyword, an unquoted identifier, a double-quoted identifier, a single-quoted string literal, a dollar-quoted string literal, a numeric literal, an operator, a parameter placeholder, a comment or a statement separator, and SHALL not evaluate any rule by substring matching over the raw statement text.
22. THE Query_Firewall SHALL exclude the content of string literals, dollar-quoted literals and double-quoted identifiers from keyword-token matching, so that a statement containing the literal value `UPDATE THE PPE POLICY` is not rejected on the basis of that literal alone.
23. THE Query_Firewall SHALL match keyword tokens case-insensitively, and SHALL treat any run of one or more whitespace characters, including line feeds and carriage returns, as a single token boundary, so that letter casing, added whitespace and added line breaks do not change the verdict.
24. IF a SQL statement contains no keyword token, contains only whitespace, or contains only comment tokens, THEN THE Query_Firewall SHALL reject the statement.
25. IF a SQL statement contains a data-modifying common table expression, including a common table expression whose body begins with `INSERT`, `UPDATE`, `DELETE` or `MERGE` with or without a `RETURNING` clause, THEN THE Query_Firewall SHALL reject the statement even though the first keyword token of the statement is `WITH`.
26. IF a SQL statement contains an `INSERT`, `UPDATE`, `DELETE`, `MERGE` or `TRUNCATE` keyword token inside a parenthesized expression, a derived table, a subquery, a set-operation arm or a common table expression at any nesting depth, THEN THE Query_Firewall SHALL reject the statement.
27. IF a SQL statement contains an `INTO` clause on a `SELECT` query, THEN THE Query_Firewall SHALL reject the statement.
28. IF a SQL statement contains a row-locking clause, including `FOR UPDATE`, `FOR NO KEY UPDATE`, `FOR SHARE` and `FOR KEY SHARE`, or a table-locking statement, THEN THE Query_Firewall SHALL reject the statement.
29. IF a SQL statement references the schema `pg_catalog`, the schema `information_schema`, or any relation identifier beginning with the character sequence `pg_`, THEN THE Query_Firewall SHALL reject the statement, irrespective of the content of the approved schema allow-list.
30. IF a SQL statement calls any of the functions `current_setting`, `set_config`, `pg_read_file`, `pg_read_binary_file`, `pg_stat_file`, `pg_ls_dir`, `lo_import`, `lo_export`, `dblink`, `dblink_connect`, `pg_sleep`, `query_to_xml`, or any function that reads the file system, executes a program, reads server configuration, changes server configuration, returns a set of rows from a system source, or performs an administrative operation, THEN THE Query_Firewall SHALL reject the statement, irrespective of the content of the approved function allow-list.
31. THE Query_Firewall SHALL source the approved function allow-list from the same single configuration artifact that supplies the approved schema allow-list.
32. THE Query_Firewall SHALL restrict the approved function allow-list to the functions required by the analytics coverage of Requirement 8, namely `count`, `sum`, `avg`, `min`, `max`, `round`, `coalesce`, `extract`, `date_trunc` and `to_char`.
33. IF a SQL statement specifies a `LIMIT` value that is not a single non-negative integer literal, including `LIMIT ALL`, a `NULL` value, an arithmetic expression, a parameter placeholder, a column reference or a subquery, THEN THE Query_Firewall SHALL reject the statement.
34. IF a SQL statement specifies an `OFFSET` value that is not a single non-negative integer literal, THEN THE Query_Firewall SHALL reject the statement.
35. IF a SQL statement joins two relations without a join predicate that references a column of each joined relation, including a comma-separated relation list whose `WHERE` clause supplies no such predicate, THEN THE Query_Firewall SHALL reject the statement.
36. IF a SQL statement exceeds the configured maximum statement length, the configured maximum join count, the configured maximum subquery nesting depth, or the configured maximum set-operation arm count, THEN THE Query_Firewall SHALL reject the statement.
37. THE Config_Loader SHALL expose the maximum statement length as configuration with a default value of `4000` characters, the maximum join count as configuration with a default value of `8` joins, the maximum subquery nesting depth as configuration with a default value of `3` levels, and the maximum set-operation arm count as configuration with a default value of `3` arms.
38. THE Query_Firewall SHALL admit a SQL statement that carries user-supplied literal values only if every such value appears as a parameter placeholder rather than as an inline literal token.
39. IF a SQL statement contains a parameter placeholder count that differs from the count of bound parameter values supplied for that statement, THEN THE Query_Firewall SHALL reject the statement.
40. IF a SQL statement contains an inline literal token whose value equals a substring of the user message of the current turn, THEN THE Query_Firewall SHALL reject the statement.
41. THE Query_Firewall SHALL restrict the recorded rejection reason code to one of `UNPARSEABLE`, `NOT_SELECT`, `MULTIPLE_STATEMENTS`, `SEPARATOR_PRESENT`, `EMPTY_STATEMENT`, `FORBIDDEN_KEYWORD`, `COMMENT_PRESENT`, `DATA_MODIFYING_CTE`, `NESTED_DML`, `SELECT_INTO`, `LOCKING_CLAUSE`, `UNAPPROVED_SCHEMA`, `SYSTEM_CATALOG_REFERENCE`, `UNAPPROVED_TABLE`, `UNAPPROVED_COLUMN`, `UNAPPROVED_FUNCTION`, `FORBIDDEN_FUNCTION`, `MISSING_LIMIT`, `LIMIT_EXCEEDS_ROW_CAP`, `NON_LITERAL_LIMIT`, `NON_LITERAL_OFFSET`, `MISSING_JOIN_PREDICATE`, `COMPLEXITY_EXCEEDED` or `UNPARAMETERIZED_LITERAL`.
42. THE Query_Firewall SHALL produce the same verdict and the same rejection reason code for repeated evaluations of the same statement text under the same configuration.
43. THE Query_Firewall SHALL be the last validation gate before warehouse execution, and THE Query_Executor SHALL execute a SQL statement only when THE Query_Firewall has produced an `ADMIT` verdict for that exact statement text within the same chat turn.
44. THE Agent_Orchestrator SHALL exclude every code path that carries a SQL statement from THE SQL_Generator to THE Query_Executor without an intervening `ADMIT` verdict from THE Query_Firewall.
45. IF THE Query_Executor receives a SQL statement whose text differs from the statement text carrying the `ADMIT` verdict of the current turn, THEN THE Query_Executor SHALL refuse execution of that statement.
46. THE LLM_API SHALL treat THE Query_Firewall as one control among several, and SHALL execute every admitted SQL statement under the read-only `llm_read` role and inside the read-only transaction required by Requirement 7, so that an admitted statement that modifies data is rejected by the warehouse as well.

### Requirement 7: Read-Only Warehouse Execution

**User Story:** As a Security Architect, I want warehouse execution to run under a role that is technically incapable of modifying data, so that a firewall defect cannot cause data loss.

Provenance: [Notion-confirmed: US-4.3 third acceptance criterion and Project Description §4.5 require a read-only database user]. The role name `llm_read`, its grant set and its secret paths are [User-directed] [New proposed requirement]; see §Open Questions OQ-9.

#### Acceptance Criteria

1. THE Query_Executor SHALL connect to the warehouse using the read-only PostgreSQL role name that THE Config_Loader resolves from configuration, for which the configured default value is `llm_read`.
2. THE Query_Executor SHALL open every warehouse session with the session characteristic `default_transaction_read_only` set to `on`.
3. THE Query_Executor SHALL execute every admitted SQL statement inside a transaction declared `READ ONLY`.
4. THE Query_Executor SHALL apply a PostgreSQL `statement_timeout` to every warehouse session.
5. THE Config_Loader SHALL expose the statement timeout as configuration with a default value of `10000` milliseconds.
6. IF the warehouse cancels a statement because the statement timeout elapsed, THEN THE Chat_Endpoint SHALL respond with HTTP status `200` and a `response` value stating that the question took too long to answer, and THE Request_Logger SHALL record the error category `TIMEOUT`.
7. THE Query_Executor SHALL request at most `row_cap + 1` rows from the warehouse for every admitted SQL statement, where `row_cap` is the configured row cap of Requirement 6.
8. THE Query_Executor SHALL resolve the read-only role credentials from AWS SSM Parameter Store or AWS Secrets Manager at runtime.
9. THE Config_Loader SHALL read the read-only role credential parameter paths, the warehouse host, the warehouse port and the warehouse database name from environment configuration, and SHALL treat every one of these keys as required.
10. IF the read-only role credentials are absent from the configured secret paths, THEN THE LLM_API SHALL report the warehouse status value `failed` on the `GET /health` route and SHALL name the absent configuration key without disclosing any secret value.
11. THE LLM_API SHALL exclude from its runtime configuration any warehouse credential whose role holds `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, `TRIGGER`, `CREATE` or DDL privileges.
12. WHEN THE Query_Executor completes a warehouse query, THE Query_Executor SHALL record the query execution outcome, the query execution duration in milliseconds and the connection acquisition duration in milliseconds in the request log entry.
13. THE Query_Executor SHALL measure the query execution duration as the interval starting when the statement is submitted on an acquired warehouse connection and ending when the last row of the result set is received or the statement fails, excluding connection acquisition time.
14. THE LLM_API SHALL require that the configured read-only role holds exactly the privileges `CONNECT` on the configured warehouse database, `USAGE` on the configured approved schema, and `SELECT` on every relation named in the approved schema allow-list of Requirement 4.
15. THE LLM_API SHALL require that the configured read-only role holds none of the privileges `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, `TRIGGER` or `CREATE` on any relation or schema of the configured warehouse database, and holds no membership in any role that holds any of those privileges.
16. WHEN THE LLM_API initializes an execution environment, THE Query_Executor SHALL execute a statically defined privilege-verification query that reports, for the connected role, whether each of `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, `TRIGGER` and `CREATE` is held directly or through role membership on any allow-listed relation or on the configured approved schema.
17. IF the privilege-verification query reports that the connected role holds any of the privileges named in criterion 16, THEN THE Query_Executor SHALL execute no admitted SQL statement for any turn, THE LLM_API SHALL report the warehouse status value `failed` on the `GET /health` route naming the privilege category that was found, and THE Chat_Endpoint SHALL respond to chat requests with HTTP status `503` and a body stating that HSE data is temporarily unavailable.
18. IF the privilege-verification query cannot be completed, THEN THE LLM_API SHALL report the warehouse status value `failed` on the `GET /health` route and SHALL treat the warehouse as unreachable for the purposes of Requirement 16.
19. IF a statement that attempts to insert, update, delete or otherwise modify warehouse data reaches the warehouse under the read-only session and transaction settings, THEN THE Query_Executor SHALL surface the warehouse read-only error as a failed query outcome, SHALL return no result set to THE Answer_Synthesizer, and THE Request_Logger SHALL record the error category `WAREHOUSE_ERROR`.
20. THE Query_Executor SHALL establish every warehouse connection with the TLS mode that THE Config_Loader resolves from configuration, for which the default value is `require`.
21. IF TLS negotiation with the warehouse fails, THEN THE Query_Executor SHALL treat the outcome as a connection failure, THE Chat_Endpoint SHALL respond with HTTP status `503` and a body stating that HSE data is temporarily unavailable, and THE Request_Logger SHALL record the error category `WAREHOUSE_ERROR`.
22. THE Query_Executor SHALL hold warehouse connections in a connection pool that persists across invocations served by the same execution environment, so that a second invocation in that execution environment reuses an established connection instead of opening a new one.
23. THE Config_Loader SHALL expose the maximum pool size as configuration with a default value of `2` connections and the minimum pool size as configuration with a default value of `1` connection.
24. THE Config_Loader SHALL expose the connection acquisition timeout as configuration with a default value of `2000` milliseconds.
25. WHEN THE Query_Executor acquires a pooled connection that was established by an earlier invocation, THE Query_Executor SHALL validate the connection with a statically defined liveness query before submitting the admitted SQL statement.
26. IF the liveness validation of a pooled connection fails, THEN THE Query_Executor SHALL discard that connection and SHALL open at most `1` replacement connection for the same turn.
27. IF THE Query_Executor cannot acquire a connection within the configured connection acquisition timeout, THEN THE Chat_Endpoint SHALL respond with HTTP status `503` and a body stating that HSE data is temporarily unavailable, and THE Request_Logger SHALL record the error category `WAREHOUSE_ERROR`.
28. IF the warehouse rejects the connection because authentication of the configured read-only role failed, THEN THE LLM_API SHALL report the warehouse status value `failed` on the `GET /health` route, THE Chat_Endpoint SHALL respond with HTTP status `503` and a body that excludes the role name, the host name, the port and the credential value, and THE Request_Logger SHALL record the error category `WAREHOUSE_ERROR`.
29. IF the warehouse rejects an admitted statement because the connected role lacks privilege on a referenced object, THEN THE Chat_Endpoint SHALL respond with HTTP status `200` and a `response` value stating that the question could not be answered against the available data, excluding the object name from the response.
30. IF the warehouse rejects an admitted statement because a referenced table or column is undefined, THEN THE Query_Executor SHALL return a failed query outcome without retrying the statement, and THE Chat_Endpoint SHALL respond with HTTP status `200` and a `response` value stating that the requested data is unavailable, excluding the identifier name from the response.
31. WHEN the configured turn timeout of Requirement 10 elapses while a warehouse statement is in flight, THE Query_Executor SHALL cancel the in-flight statement, SHALL return the connection to the pool or discard it, and THE Request_Logger SHALL record the error category `TIMEOUT`.
32. IF a returned result set contains more than `row_cap` rows, more than the configured maximum column count, or more than the configured maximum total returned bytes, THEN THE Query_Executor SHALL return at most the first `row_cap` rows and SHALL set a truncation indicator on the result object supplied to THE Answer_Synthesizer.
33. THE Config_Loader SHALL expose the maximum result column count as configuration with a default value of `50` columns and the maximum total returned bytes as configuration with a default value of `1048576` bytes.
34. THE Query_Executor SHALL exclude the warehouse host, port, database name, role name, password and full connection string from every raised exception message, from every value placed in a chat response and from every value placed in a request log entry.
35. THE Query_Executor SHALL expose no interface that accepts a caller-supplied SQL string, other than an interface that requires an accompanying `ADMIT` verdict from THE Query_Firewall for that exact statement text, and the statically defined schema-verification, privilege-verification, liveness and dimension-value queries of Requirement 4 that are declared as literals in the service source code.

### Requirement 8: Supported HSE Analytics Coverage

**User Story:** As an HSE Coordinator, I want the assistant to answer the analytics questions the warehouse can actually serve, so that I trust the figures I receive.

Provenance: [Notion-confirmed: HSE Data Warehouse — Star Schema (as built by the ETL)] for every listed table, column and measure.

#### Coverage Matrix

| Question category | Supported in MVP | Serving tables and columns |
|---|---|---|
| Accidents / incidents counts | Yes | `fact_incidents.incident_count`, `dim_incident_type.category = 'Incident'` |
| Near misses | Yes | `dim_incident_type.category = 'Near Miss'` |
| Hazards | Yes | `dim_incident_type.category = 'Hazard'` |
| Occupational injuries and illnesses | Yes | `dim_injury.injury_type`, `dim_injury.body_part` via `bridge_incident_injury.record_no` |
| Incident severity (actual) | Yes | `dim_incident_type.severity` ∈ {`minor`, `serious`, `fatal`, `unknown`} |
| Potential severity | Yes, only when the question names potential outcome | `dim_incident_type.potential_severity` ∈ {`minor`, `serious`, `fatal`, `unknown`} |
| Weighted severity figure | Yes, with scale stated | `fact_incidents.severity_index` (Fatal=100, Serious=50, Minor=10, unknown=0) |
| Trends by date, month, quarter, year | Yes | `dim_date.date`, `dim_date.day`, `dim_date.month`, `dim_date.quarter`, `dim_date.year`, `dim_date.day_name`, `dim_date.is_holiday` |
| Trends by week | Yes, derived | `EXTRACT(WEEK FROM dim_date.date)` or `date_trunc('week', dim_date.date)`; there is no week column |
| By plant, location, area | Yes, with masked plant values | `dim_location.plant` (masked), `dim_location.area_on_site` |
| By incident type | Yes | `dim_incident_type.category` |
| By shift | Yes | `dim_shift.shift_name` ∈ {`Morning`, `Night`, `unknown`}, `dim_shift.start_time`, `dim_shift.end_time` |
| By cause | Yes | `dim_cause.root_cause`, `dim_cause.subcategory` ∈ {`Unsafe Act`, `Unsafe Condition`}, `dim_cause.criticality_level` |
| By status | Yes | `dim_status.status` ∈ {`Open`, `Closed`, `Investigation`}, `dim_status.investigation_required` |
| By equipment | Yes | `dim_equipment.equipment_name`, `dim_equipment.other_equipment`, `dim_equipment.sub_equipment`, `dim_equipment.machine_code`, `dim_equipment.is_equipment_involved`, `dim_equipment.equipment_category` |
| By PPE | Yes | `dim_ppe.ppe_description`, `dim_ppe.ppe_type`, `bridge_incident_ppe.is_ppe_worn` |
| By high-risk area | Yes | `dim_high_risk_area.high_risk_area_category`, `dim_high_risk_area.high_risk_area_category_standardized` |
| Corrective actions | Yes | `fact_actions.action_count`, `dim_action_details.action_english_description`, `dim_action_details.action_local_language_description` |
| Spanish-language questions over English stored values | Yes, by vocabulary mapping | Mapping rules in AC 15–18, 23 |
| Comparison across two time ranges or two locations | Yes, derived | Two grouped rows over `dim_date` or `dim_location`; no comparison measure exists |
| Top-N / ranking by a supported dimension | Yes, derived | `ORDER BY` on a supported measure plus bounded `LIMIT` |
| Assistant capability description | Yes, without warehouse access | Supported rows of this matrix only |
| Lost workdays | **No** | No lost-workday measure exists; `S3b` collapses into `serious` — see OQ-1 |
| Lost-time (LTA) case identification | **No** | `S3b` is indistinguishable from other `serious` rows — see OQ-1 |
| Employee-level analytics | **No** | No employee dimension exists in the authoritative schema — see OQ-2 |
| Free-text narrative search | **No** | `dim_text_event` is excluded from the allow-list |
| Individual incident free-text description | **No** | `dim_text_event` is excluded from the allow-list |
| Frequency rate | **No** | Intentionally excluded from `fact_incidents` |
| Injury-rate / TRIR-style computed KPI | **No** | No exposure-hours or headcount measure exists in the schema |
| Incident cause or severity prediction | **No** | Prediction is served by the separate ML API, not by `LLM_API` |

#### Acceptance Criteria

1. WHEN a question requests a count of incidents, near misses or hazards, THE SQL_Generator SHALL aggregate `fact_incidents.incident_count` and SHALL filter `dim_incident_type.category` to exactly one of the values `Incident`, `Near Miss` or `Hazard`.
2. WHEN a question requests an incident-severity figure, THE SQL_Generator SHALL serve the figure from `dim_incident_type.severity`, `dim_incident_type.potential_severity` or `fact_incidents.severity_index` and from no other column.
3. WHEN a question requests occupational-injury information, THE SQL_Generator SHALL read `dim_injury.injury_type` and `dim_injury.body_part` and SHALL join `dim_injury` to `fact_incidents` through `bridge_incident_injury.record_no`.
4. WHEN a question requests personal-protective-equipment information, THE SQL_Generator SHALL read `dim_ppe.ppe_description`, `dim_ppe.ppe_type` and `bridge_incident_ppe.is_ppe_worn` and SHALL join `dim_ppe` to `fact_incidents` through `bridge_incident_ppe.record_no`.
5. WHEN a question requests corrective-action information, THE SQL_Generator SHALL aggregate `fact_actions.action_count` and SHALL read action descriptions from `dim_action_details.action_english_description` or `dim_action_details.action_local_language_description`.
6. IF a question requests a lost-workday figure or the identification of lost-time cases, THEN THE Answer_Synthesizer SHALL produce an answer stating that the lost-workday metric is unavailable in the current data warehouse, and SHALL exclude every numeric figure from that answer.
7. IF a question requests employee-level, employee-attribute or per-person analytics, THEN THE Answer_Synthesizer SHALL produce an answer stating that employee-level analytics are unavailable in the current data warehouse, and SHALL exclude every numeric figure from that answer.
8. IF a question requests a frequency rate, an injury rate, a severity rate, an incident rate per worked hours, or any rate expressed against exposure hours or headcount, THEN THE Answer_Synthesizer SHALL produce an answer stating that rate metrics are unavailable in the current data warehouse, and SHALL exclude every numeric figure from that answer.
9. IF a question requests search over, or aggregation of, free-text incident narrative content, THEN THE Answer_Synthesizer SHALL produce an answer stating that narrative-text retrieval is unavailable in the current release, and SHALL exclude every narrative excerpt from that answer.
10. WHEN a question names a plant or a location, THE SQL_Generator SHALL filter on `dim_location.plant` or `dim_location.area_on_site` using a value that is present in `dim_location`.
11. IF a named plant or location matches no value present in `dim_location.plant` and no value present in `dim_location.area_on_site`, THEN THE Answer_Synthesizer SHALL produce an answer stating that the location was not recognized, SHALL list at least `1` and at most `10` location values that are present in `dim_location`, and SHALL exclude every numeric figure from that answer.
12. WHEN THE Answer_Synthesizer reports a figure sourced from a warehouse result set, THE Answer_Synthesizer SHALL state in the same answer that the figure covers finalized Colombia and "The Americas" incidents.
13. IF a question names a country, region or site outside Colombia and "The Americas", THEN THE Answer_Synthesizer SHALL produce an answer stating that the data warehouse contains finalized Colombia and "The Americas" incidents only, and SHALL exclude every numeric figure from that answer.
14. IF a question requests a measure that is absent from the approved schema allow-list, THEN THE Answer_Synthesizer SHALL produce an answer stating that the requested metric is unavailable, and SHALL exclude every figure computed from any other measure from that answer.
15. WHEN a question uses the Spanish terms `accidente`, `accidentes`, `incidente` or `incidentes`, THE Intent_Classifier SHALL emit `dim_incident_type.category` equal to `Incident`; WHEN a question uses `casi accidente`, `cuasi accidente` or `casi accidentes`, THE Intent_Classifier SHALL emit `dim_incident_type.category` equal to `Near Miss`; WHEN a question uses `peligro`, `peligros` or `condición peligrosa`, THE Intent_Classifier SHALL emit `dim_incident_type.category` equal to `Hazard`.
16. WHEN a question uses the Spanish term `gravedad` or `severidad`, THE Intent_Classifier SHALL emit `dim_incident_type.severity` as the requested attribute, and SHALL map the value terms `leve` to `minor`, `grave` and `serio` to `serious`, and `fatal` and `mortal` to `fatal`.
17. WHEN a question uses the Spanish term `turno`, THE Intent_Classifier SHALL emit `dim_shift.shift_name` as the requested attribute, and SHALL map `mañana` and `día` to the value `Morning`, which covers `06:00` to `17:59`, and `noche` to the value `Night`, which covers `18:00` to `05:59`.
18. WHEN a question uses a Spanish dimension term, THE Intent_Classifier SHALL map the term to exactly one allow-listed column as follows: `planta` to `dim_location.plant`; `área` and `area` to `dim_location.area_on_site`; `causa raíz` to `dim_cause.root_cause`; `acto inseguro` to `dim_cause.subcategory` value `Unsafe Act`; `condición insegura` to `dim_cause.subcategory` value `Unsafe Condition`; `estado` to `dim_status.status`; `lesión` to `dim_injury.injury_type`; `parte del cuerpo` to `dim_injury.body_part`; `EPP` to `dim_ppe`; `equipo` and `máquina` to `dim_equipment`; `acciones correctivas` to `fact_actions`.
19. WHEN a question requests severity without naming a potential, hypothetical or worst-case outcome, THE SQL_Generator SHALL filter and group on `dim_incident_type.severity` and SHALL exclude `dim_incident_type.potential_severity` from the statement.
20. WHEN a question names a potential, hypothetical or worst-case outcome, including the Spanish terms `gravedad potencial` or `severidad potencial`, THE SQL_Generator SHALL filter and group on `dim_incident_type.potential_severity`, and THE Answer_Synthesizer SHALL state in the answer that the reported figure describes potential severity rather than actual severity.
21. WHEN THE Answer_Synthesizer reports a figure sourced from `fact_incidents.severity_index`, THE Answer_Synthesizer SHALL state in the same answer that the figure is a weighted index using the per-incident weights `fatal` equal to `100`, `serious` equal to `50`, `minor` equal to `10` and `unknown` equal to `0`.
22. WHEN THE Answer_Synthesizer reports a figure filtered on the `dim_incident_type.severity` value `serious`, THE Answer_Synthesizer SHALL exclude from the answer any statement that equates `serious` with lost-time cases, lost workdays or lost-time accidents.
23. WHEN a question names a raw Intelex severity code, THE Intent_Classifier SHALL map `S0` and `S1` to the `dim_incident_type.severity` value `minor`, `S2`, `S3a` and `S3b` to `serious`, `S4` and `S5` to `fatal`, and any other code to `unknown`, and THE Answer_Synthesizer SHALL state in the answer the mapped severity value that the figure covers.
24. IF a question requests a prediction, forecast, projection, classification of a future outcome, or a predicted cause or predicted severity, THEN THE Answer_Synthesizer SHALL produce an answer stating that prediction is not provided by this assistant, and SHALL exclude every numeric figure from that answer.
25. IF a question requests the free-text description, narrative, comment or report body of an individual incident, THEN THE Answer_Synthesizer SHALL produce an answer stating that incident description text is unavailable in the current release, and SHALL exclude every narrative excerpt from that answer.
26. IF a question names a plant, area, shift name, root cause, cause subcategory, status, injury type, body part, PPE description, PPE type, equipment name or high-risk-area category that matches no value present in the corresponding dimension table, THEN THE Answer_Synthesizer SHALL produce an answer stating that the named value was not recognized, SHALL name the attribute that was not recognized, SHALL list at least `1` and at most `10` values present in that dimension, and SHALL exclude every numeric figure from that answer.
27. IF a question names a single location term that matches at least one value in `dim_location.plant` and at least one value in `dim_location.area_on_site`, THEN THE Answer_Synthesizer SHALL produce an answer asking the user to choose between the plant interpretation and the area interpretation, and SHALL exclude every numeric figure from that answer.
28. WHEN THE Query_Executor returns a result set containing at least one row whose reported aggregate value equals `0`, THE Answer_Synthesizer SHALL state the figure `0` together with the applied filters, and SHALL exclude from the answer any statement that no matching records exist.
29. WHEN THE Query_Executor returns a result set containing zero rows for a supported question, THE Answer_Synthesizer SHALL state that no records match the applied filters, and SHALL exclude every aggregate figure other than an explicit count of `0` from the answer.
30. WHEN a question requests a comparison between two time ranges, THE Intent_Classifier SHALL emit one absolute start date and one absolute end date per range, THE SQL_Generator SHALL produce one statement that returns one aggregate row per range, and THE Answer_Synthesizer SHALL state both figures and the arithmetic difference between them.
31. WHEN a question requests a comparison between two named plants or two named areas, THE SQL_Generator SHALL produce one statement grouped by `dim_location.plant` or `dim_location.area_on_site` that returns one aggregate row per named value, and THE Answer_Synthesizer SHALL state each figure alongside the location value it belongs to.
32. WHEN a question requests a ranking, a highest-value list or a lowest-value list, THE SQL_Generator SHALL order the result set by the requested measure, SHALL set the `LIMIT` clause to the row count the question names, and SHALL set the `LIMIT` clause to `5` when the question names no row count.
33. THE Config_Loader SHALL expose the maximum ranking size as configuration with a default value of `25` rows, and WHEN a question requests a ranking size greater than the configured maximum, THE SQL_Generator SHALL set the `LIMIT` clause to the configured maximum and THE Answer_Synthesizer SHALL state the number of ranked rows reported.
34. WHEN a question asks which questions THE LLM_API can answer, THE Answer_Synthesizer SHALL name only question categories that the coverage matrix of this requirement marks as supported, SHALL exclude table names and column names from the answer, and THE Agent_Orchestrator SHALL produce the answer without executing a warehouse query.
35. WHEN THE Answer_Synthesizer produces an answer stating that a metric is unavailable, THE Answer_Synthesizer SHALL exclude from that answer any figure sourced from `incident_count`, `severity_index` or `action_count` presented as a substitute for the requested metric.
36. WHEN a corrective-action result row carries the `dim_action_details.action_english_description` value `No action` or the `dim_action_details.action_local_language_description` value `Sin acción`, THE Answer_Synthesizer SHALL report the corresponding `record_no` as having `0` corrective actions rather than omitting it from the answer.
37. WHEN an injury result row carries the `dim_injury.injury_type` value `Unknown` or the `dim_injury.body_part` value `No Body Part`, THE Answer_Synthesizer SHALL report that row as an unspecified injury type or unspecified body part rather than omitting it from the answer.

### Requirement 9: Natural-Language Answer Synthesis

**User Story:** As a user, I want the bot to answer with a natural sentence that includes the data found rather than a raw table, so that the experience is conversational.

Provenance: [Notion-confirmed: US-4.4 "Síntesis de Respuesta (Natural Language Response)", 3 pts, Sprint 10].

#### Acceptance Criteria

1. WHEN THE Query_Executor returns a result set containing at least one row, THE Answer_Synthesizer SHALL produce a natural-language answer that states each reported figure using a value present in that result set.
2. WHEN THE Query_Executor returns a result set containing at least one row, THE Answer_Synthesizer SHALL produce a natural-language answer that names the applied filters, stating the resolved time range when the query applied a date filter and stating the location value as returned in the result set, rather than the phrasing used in the user message, when the query applied a location filter.
3. WHEN THE Query_Executor returns a result set containing zero rows, THE Answer_Synthesizer SHALL produce a natural-language answer stating that no matching records were found and restating the resolved time range and the location filter applied to the query.
4. THE Answer_Synthesizer SHALL produce answers of at most `600` characters.
5. WHERE the configuration value `answer_language` is `auto`, THE Answer_Synthesizer SHALL produce answers in the language of the user message.
6. WHERE the configuration value `answer_language` is set to a fixed language code, THE Answer_Synthesizer SHALL produce answers in that language irrespective of the language of the user message.
7. THE Config_Loader SHALL expose the `answer_language` value as configuration restricted to the values `auto`, `es` and `en`, with the default value `auto`.
8. THE Answer_Synthesizer SHALL produce answers that exclude table names, column names, SQL statement text, schema identifiers, host names, credential values, configuration values, internal reason-code values, error category values and model reasoning text.
9. THE Answer_Synthesizer SHALL produce answers whose stated figures equal the figures present in the warehouse result set.
10. IF THE Query_Executor returns a result set whose row count equals the configured row cap, THEN THE Answer_Synthesizer SHALL state that the answer reports the first `1000` rows of a larger result set, using the configured row cap value in place of `1000` when the configuration differs.
11. WHEN THE Intent_Classifier classifies a message as `GENERAL_CHAT`, THE Answer_Synthesizer SHALL produce an answer naming the supported analytics categories, covering incident, near-miss and hazard counts, incident severity, occupational injuries, personal protective equipment, corrective actions, and breakdowns by date, location, shift, cause, status, equipment and high-risk area, and SHALL exclude any offer of lost-workday analytics, employee-level analytics, frequency-rate analytics and free-text narrative retrieval.
12. WHEN THE Model_Provider_Adapter returns a draft answer for a synthesis request, THE Answer_Synthesizer SHALL verify, before THE Chat_Endpoint responds, that every numeric literal in the draft answer equals a numeric value present in the result set, a boundary date of the resolved time range of the structured analytics intent, or the configured row cap.
13. IF a numeric literal in the draft answer equals none of the values permitted by acceptance criterion 12, THEN THE Answer_Synthesizer SHALL request one additional draft answer for the same turn.
14. IF a numeric literal in the second draft answer equals none of the values permitted by acceptance criterion 12, THEN THE Answer_Synthesizer SHALL discard the draft answer and render the answer from its deterministic template without any further model-provider call.
15. IF verification fails for both draft answers and the result set has more than one row or more than one numeric column, THEN THE Answer_Synthesizer SHALL produce an answer stating that the figures could not be confirmed and SHALL exclude every numeric literal from that answer.
16. WHEN THE Query_Executor returns a result set containing exactly one row and exactly one numeric column, THE Answer_Synthesizer SHALL render the answer from its deterministic template, taking the stated figure from the result-set value and issuing no model-provider call.
17. THE Answer_Synthesizer SHALL produce answers that exclude any percentage, rate, ratio, trend claim, period-over-period comparison, cause attribution, recommendation and forecast that is not present as a value in the result set.
18. WHERE the answer language resolves to `es`, THE Answer_Synthesizer SHALL render numeric values using `.` as the thousands separator and `,` as the decimal separator.
19. WHERE the answer language resolves to `en`, THE Answer_Synthesizer SHALL render numeric values using `,` as the thousands separator and `.` as the decimal separator.
20. THE Answer_Synthesizer SHALL render an integer result value without a fractional part and SHALL render a non-integer result value with exactly `2` fractional digits.
21. WHEN the resolved time range starts on the first calendar day of a month and ends on the last calendar day of that same month, THE Answer_Synthesizer SHALL render the range as the name of that month in the answer language followed by the four-digit year, so that `2026-02-01` to `2026-02-28` renders as `febrero de 2026` when the answer language resolves to `es`.
22. WHEN the resolved time range starts on the first calendar day of a year and ends on the last calendar day of that same year, THE Answer_Synthesizer SHALL render the range as the four-digit year alone.
23. WHEN the resolved time range spans neither a full calendar month nor a full calendar year, THE Answer_Synthesizer SHALL render the range as its start date and its end date, each in `YYYY-MM-DD` form.
24. WHEN THE Query_Executor returns a result set containing more than one row, THE Answer_Synthesizer SHALL enumerate inline at most the configured maximum number of grouped rows, ordered by the reported measure value in descending order, and SHALL state the total count of grouped rows present in the result set when that count exceeds the configured maximum.
25. THE Config_Loader SHALL expose the maximum count of inline-enumerated grouped rows as configuration with a default value of `5`.
26. IF a rendered answer would exceed `600` characters, THEN THE Answer_Synthesizer SHALL reduce the count of inline-enumerated grouped rows until the rendered answer is at most `600` characters, and SHALL state the count of grouped rows it did not enumerate.
27. WHERE an answer reports a `severity_index` value, THE Answer_Synthesizer SHALL identify the value as a weighted severity index and SHALL exclude describing the value as a number of events; WHERE an answer reports an `incident_count` or `action_count` value, THE Answer_Synthesizer SHALL identify the value as a count of events.
28. WHEN THE Query_Executor returns a result set containing exactly one row whose reported measure value is `0`, THE Answer_Synthesizer SHALL produce an answer stating that zero events matched the applied filters, using wording distinct from the zero-row wording of acceptance criterion 3.
29. WHEN a grouped result row carries a null grouping value or the grouping value `unknown`, THE Answer_Synthesizer SHALL label that group with an unknown-value label in the answer language and SHALL exclude the literal tokens `NULL`, `None` and the empty string from the answer.
30. THE Answer_Synthesizer SHALL issue at most `2` model-provider calls per chat turn, counted within the per-turn model-call maximum of Requirement 10.
31. IF a synthesis model-provider call fails or exceeds the configured provider request timeout and the result set contains exactly one row and exactly one numeric column, THEN THE Answer_Synthesizer SHALL render the answer from its deterministic template and THE Chat_Endpoint SHALL respond with HTTP status `200`.
32. IF a synthesis model-provider call fails or exceeds the configured provider request timeout and the result set has more than one row or more than one numeric column, THEN THE Chat_Endpoint SHALL respond with HTTP status `503` and a body stating that the assistant is temporarily unavailable.
33. THE Answer_Synthesizer SHALL emit answer text encoded in UTF-8, preserving Spanish diacritic characters and `ñ` without escape sequences and without replacement characters.

### Requirement 10: Controlled Agent Workflow

**User Story:** As a Developer, I want the agent to execute a fixed, auditable node sequence, so that every turn follows the same safety path and failures are diagnosable.

Provenance: [User-directed] LangGraph orchestration, superseding the LangChain note in Project Description §2.2 and US-4.1; see §Open Questions OQ-10.

#### Acceptance Criteria

1. THE Agent_Orchestrator SHALL execute each chat turn as a LangGraph state graph containing exactly the nine nodes `scope_validation`, `intent_classification`, `schema_context_selection`, `query_generation`, `query_validation`, `query_execution`, `answer_synthesis`, `conversation_context_update` and `terminal_error`.
2. THE Agent_Orchestrator SHALL order the nodes traversed by a successful `DATA_QUERY` turn as `scope_validation`, `intent_classification`, `schema_context_selection`, `query_generation`, `query_validation`, `query_execution`, `answer_synthesis`, `conversation_context_update`, with `scope_validation` as the sole graph entry node and `conversation_context_update` as the sole graph exit node.
3. THE Agent_Orchestrator SHALL permit entry to the `query_execution` node only along a path on which the `scope_validation` node has written the scope decision `IN_SCOPE` and the `query_validation` node has written the firewall verdict `ADMIT` for the SQL statement held in graph state.
4. THE Agent_Orchestrator SHALL exclude every tool invocation and every node that sends a SQL statement supplied by THE Model_Provider_Adapter to THE Query_Executor without a preceding `ADMIT` verdict written by the `query_validation` node.
5. THE Agent_Orchestrator SHALL limit the number of THE Model_Provider_Adapter calls per turn to the configured per-turn model-call maximum, counting every call including calls made during query regeneration.
6. THE Config_Loader SHALL expose the per-turn model-call maximum as configuration with a default value of `4` and SHALL admit only integer values in the inclusive range `1` to `10`.
7. IF the per-turn model-call count reaches the configured per-turn model-call maximum before the graph state field `answer_text` holds a value, THEN THE Agent_Orchestrator SHALL transition to the `terminal_error` node, SHALL set the turn outcome to `MODEL_CALL_LIMIT_REACHED`, and THE Chat_Endpoint SHALL respond with HTTP status `200` and a `response` value stating that the question could not be answered.
8. WHEN a chat turn reaches the graph exit node, THE Agent_Orchestrator SHALL record the turn outcome value held in graph state as the agent workflow outcome in the request log entry.
9. THE Agent_Orchestrator SHALL complete each chat turn, including the `conversation_context_update` node, within the configured turn timeout measured from the instant THE Chat_Endpoint accepts the validated request body.
10. THE Config_Loader SHALL expose the turn timeout as configuration with a default value of `25000` milliseconds.
11. IF a turn exceeds the configured turn timeout, THEN THE Agent_Orchestrator SHALL set the turn outcome to `TURN_TIMEOUT` and THE Chat_Endpoint SHALL respond with HTTP status `504` and a body stating that the request timed out.
12. THE Agent_Orchestrator SHALL represent the graph state as a single Pydantic model and SHALL validate the state object at the entry and the exit of every node.
13. THE Agent_Orchestrator SHALL permit exactly the following transitions and no others:
    - graph entry → `scope_validation`
    - `scope_validation` → `intent_classification`, when the written scope decision is `IN_SCOPE`
    - `scope_validation` → `terminal_error`, when the written scope decision is `OUT_OF_SCOPE` or `UNSAFE`
    - `intent_classification` → `schema_context_selection`, when the written intent is `DATA_QUERY`
    - `intent_classification` → `answer_synthesis`, when the written intent is `GENERAL_CHAT`
    - `intent_classification` → `terminal_error`, when the written intent is `CLARIFICATION_NEEDED` or when the analytics intent fails Pydantic validation
    - `schema_context_selection` → `query_generation`
    - `schema_context_selection` → `terminal_error`
    - `query_generation` → `query_validation`
    - `query_generation` → `terminal_error`
    - `query_validation` → `query_execution`, when the written firewall verdict is `ADMIT`
    - `query_validation` → `query_generation`, when the written firewall verdict is `REJECT` and the regeneration count is `0`
    - `query_validation` → `terminal_error`, when the written firewall verdict is `REJECT` and the regeneration count is `1`
    - `query_execution` → `answer_synthesis`
    - `query_execution` → `terminal_error`
    - `answer_synthesis` → `conversation_context_update`
    - `answer_synthesis` → `terminal_error`
    - `terminal_error` → `conversation_context_update`
    - `conversation_context_update` → graph exit
14. THE Agent_Orchestrator SHALL select the next node of every transition from the validated output of the completed node and from the graph state only, and SHALL exclude the output of THE Model_Provider_Adapter from next-node selection.
15. THE Agent_Orchestrator SHALL exclude any node whose entry is requested by content of a model completion, of a user message or of a conversation-context entry.
16. THE Agent_Orchestrator SHALL contain exactly one cyclic edge, the `query_validation` → `query_generation` regeneration edge, and SHALL contain no other path by which a node is entered twice within one turn.
17. THE Agent_Orchestrator SHALL traverse the `query_validation` → `query_generation` regeneration edge at most `1` time per turn, and SHALL increment the graph state regeneration count on each traversal.
18. THE Agent_Orchestrator SHALL carry exactly the graph state fields `request_id`, `conversation_id`, `user_id`, `raw_message`, `turn_started_at`, `conversation_context`, `scope_decision`, `intent`, `analytics_intent`, `schema_context`, `generated_sql`, `firewall_verdict`, `regeneration_count`, `result_set`, `result_row_count`, `query_duration_ms`, `answer_text`, `model_call_count`, `error_category` and `turn_outcome`.
19. THE Agent_Orchestrator SHALL permit each node to write only the graph state fields listed for that node and SHALL reject a node output that writes any other field:
    - `scope_validation`: `scope_decision`
    - `intent_classification`: `intent`, `analytics_intent`, `model_call_count`
    - `schema_context_selection`: `schema_context`
    - `query_generation`: `generated_sql`, `regeneration_count`, `model_call_count`
    - `query_validation`: `firewall_verdict`
    - `query_execution`: `result_set`, `result_row_count`, `query_duration_ms`
    - `answer_synthesis`: `answer_text`, `model_call_count`, `turn_outcome`
    - `terminal_error`: `answer_text`, `error_category`, `turn_outcome`
    - `conversation_context_update`: `conversation_context`
20. THE Agent_Orchestrator SHALL treat the graph state field `scope_decision` as write-once, and IF a node output writes `scope_decision` after the `scope_validation` node has written it, THEN THE Agent_Orchestrator SHALL discard the node output, transition to the `terminal_error` node and set the turn outcome to `INTERNAL_ERROR`.
21. THE Agent_Orchestrator SHALL treat the graph state field `firewall_verdict` as write-once per regeneration attempt, and IF a node other than `query_validation` writes `firewall_verdict`, THEN THE Agent_Orchestrator SHALL discard the node output, transition to the `terminal_error` node and set the turn outcome to `INTERNAL_ERROR`.
22. THE Agent_Orchestrator SHALL write the graph state field `turn_outcome` exactly once per turn, and IF a second write of `turn_outcome` is attempted, THEN THE Agent_Orchestrator SHALL retain the first written value.
23. THE Agent_Orchestrator SHALL traverse the `conversation_context_update` node on every terminal path, including the scope-rejection path, the clarification path, the firewall-rejection path, the warehouse-error path, the timeout path and the unhandled-exception path, so that every turn that reaches the graph is recorded in THE Conversation_Store.
24. WHEN a turn terminates through the `terminal_error` node, THE Conversation_Store SHALL record the turn with the user message, the responded answer text, the `scope_decision`, the `intent` and the `turn_outcome`, and SHALL exclude the generated SQL statement, the schema context and the warehouse result set from the recorded turn.
25. THE Agent_Orchestrator SHALL produce no side effect outside the process other than the read-only warehouse query issued by THE Query_Executor, the model completions requested through THE Model_Provider_Adapter, the conversation-context write performed by THE Conversation_Store and the log entry emitted by THE Request_Logger.
26. WHILE THE Model_Provider_Adapter is configured to its deterministic stub implementation and THE Query_Executor is configured to a stub warehouse, THE Agent_Orchestrator SHALL produce the same traversed node sequence, the same `turn_outcome` and the same `answer_text` for repeated executions of an identical request body and identical conversation context.
27. THE Config_Loader SHALL admit a configuration set only if the configured warehouse statement timeout of Requirement 7 is strictly less than the configured turn timeout, and IF the statement timeout is greater than or equal to the turn timeout, THEN THE LLM_API SHALL report a failed status on the `GET /health` route naming the two configuration keys.
28. THE Config_Loader SHALL admit turn timeout values in the inclusive range `1000` to `29000` milliseconds, bounded above by the API Gateway integration timeout of `29000` milliseconds, and SHALL reject values outside that range at startup.
29. WHEN a turn terminates on the turn timeout, on the per-turn model-call maximum, or on an unhandled exception while a warehouse statement is in flight, THE Query_Executor SHALL cancel the in-flight statement and release the warehouse connection within `1000` milliseconds of the termination.
30. WHEN two chat requests carrying the same `conversation_id` are processed concurrently in one execution environment, THE Agent_Orchestrator SHALL supply each turn with the conversation context read at that turn's `scope_validation` node entry, and THE Conversation_Store SHALL record both completed turns subject to the per-conversation turn maximum of Requirement 12.
31. WHEN chat requests carrying distinct `conversation_id` values are processed concurrently in one execution environment, THE Agent_Orchestrator SHALL allocate one graph state object per turn and SHALL share no mutable graph state field between turns.
32. IF a node raises an unhandled exception, THEN THE Agent_Orchestrator SHALL transition to the `terminal_error` node, SHALL set `error_category` to `INTERNAL_ERROR`, SHALL set `turn_outcome` to `INTERNAL_ERROR`, and THE Chat_Endpoint SHALL respond with a `response` value that excludes stack traces, exception text, SQL statement text, schema identifiers, host names and credential values.
33. THE Agent_Orchestrator SHALL restrict the `turn_outcome` value to one of `ANSWERED_DATA_QUERY`, `ANSWERED_GENERAL_CHAT`, `CLARIFICATION_REQUESTED`, `SCOPE_REJECTED`, `INTENT_UNRESOLVED`, `FIREWALL_REJECTED`, `WAREHOUSE_ERROR`, `WAREHOUSE_TIMEOUT`, `PROVIDER_ERROR`, `TURN_TIMEOUT`, `MODEL_CALL_LIMIT_REACHED` or `INTERNAL_ERROR`.

### Requirement 11: Model Provider Abstraction

**User Story:** As a Developer, I want model access behind a provider abstraction, so that the service can move from an OpenAI-compatible provider to AWS Bedrock without changing agent logic.

Provenance: [User-directed]; [Notion-confirmed: Project Description §2.2 names OpenAI and AWS Bedrock as the provider options]. The chosen provider and model are unresolved; see §Open Questions OQ-12.

#### Acceptance Criteria

1. THE Agent_Orchestrator SHALL request every model completion through THE Model_Provider_Adapter and SHALL issue no model-provider call outside THE Model_Provider_Adapter.
2. THE Model_Provider_Adapter SHALL expose a single provider-independent interface for structured-output completion requests.
3. THE Config_Loader SHALL read the provider identifier, the model identifier, the provider endpoint reference, the provider credential reference, the request timeout, the maximum output tokens, the sampling temperature and the prompt version identifier from environment configuration.
4. THE Model_Provider_Adapter SHALL resolve the provider credential from AWS SSM Parameter Store or AWS Secrets Manager at runtime.
5. THE LLM_API SHALL exclude hard-coded provider names, model names, endpoint URLs and credentials from its source code.
6. IF THE Model_Provider_Adapter receives a retryable error response from the provider, THEN THE Model_Provider_Adapter SHALL retry the request at most `2` additional times, waiting `500` milliseconds before the first retry and `1000` milliseconds before the second retry, plus a random additional delay between `0` and `250` milliseconds before each retry.
7. IF THE Model_Provider_Adapter exhausts its retries, THEN THE Chat_Endpoint SHALL respond with HTTP status `503` and a body stating that the assistant is temporarily unavailable.
8. THE Model_Provider_Adapter SHALL apply a per-request timeout to every provider call.
9. THE Config_Loader SHALL expose the provider request timeout as configuration with a default value of `15000` milliseconds.
10. THE Model_Provider_Adapter SHALL record the prompt token count and the completion token count of each provider call in the request log entry.
11. THE Model_Provider_Adapter SHALL support substitution by a deterministic stub implementation selected through configuration, so that automated tests run without calling a live provider.
12. THE Model_Provider_Adapter SHALL accept a structured-output completion request carrying exactly the following inputs: one system instruction text value, one ordered message list whose entries each carry a role value of `user` or `assistant` and a content text value, one target Pydantic output model, one sampling temperature value, one maximum output token count, one request timeout in milliseconds, and the request identifier of the current turn.
13. THE Model_Provider_Adapter SHALL return a structured-output completion response carrying exactly the following outputs: one validated instance of the target Pydantic output model, the prompt token count, the completion token count, one finish reason restricted to the values `COMPLETED`, `MAX_OUTPUT_TOKENS`, `CONTENT_FILTERED` or `ERROR`, and the provider-assigned request identifier as a string, set to an empty string when the provider supplies none.
14. THE Config_Loader SHALL expose the sampling temperature as configuration with a default value of `0.0` and the maximum output tokens as configuration with a default value of `1024`.
15. THE Model_Provider_Adapter SHALL return a structured-output completion response only after the provider output has been parsed into an instance of the target Pydantic output model that passes that model's validation.
16. IF the provider output fails to parse into the target Pydantic output model, THEN THE Model_Provider_Adapter SHALL issue at most `1` additional repair request for that completion, restating the target output model, and SHALL count that repair request against the per-turn model-call maximum of Requirement 10.
17. IF the repair request output also fails to parse into the target Pydantic output model, THEN THE Model_Provider_Adapter SHALL return a failure for the completion, THE Agent_Orchestrator SHALL terminate the turn, THE Chat_Endpoint SHALL respond with a `response` value stating that the question could not be interpreted, and THE Request_Logger SHALL record the error category `PROVIDER_ERROR`.
18. IF a provider call fails with a connection error, a transport error, a request timeout, a rate-limit error or a provider server-side error, THEN THE Model_Provider_Adapter SHALL classify the failure as retryable and SHALL apply the retry behaviour of acceptance criterion 6.
19. IF a provider call fails with an authentication failure, an invalid-request error, a content-filter refusal, or an output-validation failure after the repair budget of acceptance criterion 16 is exhausted, THEN THE Model_Provider_Adapter SHALL classify the failure as non-retryable and SHALL issue no retry under acceptance criterion 6.
20. IF THE Model_Provider_Adapter receives a provider response whose finish reason is `CONTENT_FILTERED`, THEN THE Chat_Endpoint SHALL respond with HTTP status `200`, `intent` set to `REJECTED` and a `response` value stating that the assistant cannot answer that request, and SHALL NOT respond with HTTP status `503`.
21. IF THE Model_Provider_Adapter receives a provider response whose finish reason is `MAX_OUTPUT_TOKENS`, THEN THE Model_Provider_Adapter SHALL discard the returned content without parsing it and SHALL reissue the same completion request at most `1` additional time for that turn.
22. IF the reissued completion request of acceptance criterion 21 also returns the finish reason `MAX_OUTPUT_TOKENS`, THEN THE Agent_Orchestrator SHALL terminate the turn and THE Chat_Endpoint SHALL respond with a `response` value stating that the question could not be answered.
23. THE Model_Provider_Adapter SHALL provide an OpenAI-compatible implementation and an AWS Bedrock implementation that satisfy the single interface of acceptance criterion 2 with identical request inputs and identical response outputs, and THE Model_Provider_Adapter SHALL select the active implementation from the configured provider identifier at startup.
24. THE LLM_API SHALL confine the addition of a further provider implementation to THE Model_Provider_Adapter and THE Config_Loader, requiring no change to THE Agent_Orchestrator, THE Scope_Guard, THE Intent_Classifier, THE SQL_Generator or THE Answer_Synthesizer.
25. THE Model_Provider_Adapter SHALL resolve the provider credential and the provider endpoint once per execution environment and SHALL reuse the resolved values for every subsequent provider call in that execution environment.
26. IF a provider call fails with an authentication failure, THEN THE Model_Provider_Adapter SHALL discard the cached credential, resolve the credential again from the configured secret reference, and reissue the call at most `1` additional time; and IF that reissued call also fails with an authentication failure, THEN THE Chat_Endpoint SHALL respond with HTTP status `503` and a body stating that the assistant is temporarily unavailable.
27. THE Model_Provider_Adapter SHALL exclude the provider credential value, the provider endpoint value, the system instruction text and the prompt template text from every request log entry and from every response body.
28. THE Model_Provider_Adapter SHALL bound the sum of prompt token counts and completion token counts across all provider calls of one turn by a configured per-turn token ceiling, and THE Config_Loader SHALL expose the per-turn token ceiling as configuration with a default value of `12000` tokens.
29. IF a turn reaches the configured per-turn token ceiling, THEN THE Model_Provider_Adapter SHALL issue no further provider call for that turn, THE Agent_Orchestrator SHALL terminate the turn, THE Chat_Endpoint SHALL respond with a `response` value stating that the question could not be answered, and THE Request_Logger SHALL record the error category `PROVIDER_ERROR`.
30. WHERE the configured provider identifier is the value `stub`, THE Model_Provider_Adapter SHALL return configured canned structured outputs without any network call, SHALL return the identical output for an identical request on every invocation, and SHALL support configured canned outputs containing SQL statements that violate the rules of Requirement 6.
31. IF the configured provider identifier is the value `stub` while the configured deployment environment value is `production`, THEN THE LLM_API SHALL report a failed model-provider status on the `GET /health` route and THE Chat_Endpoint SHALL respond to `POST /chat/message` with HTTP status `503` and a body stating that the assistant is temporarily unavailable.
32. THE Request_Logger SHALL include the configured prompt version identifier in every request log entry for a turn that issued at least one provider call.
33. THE Model_Provider_Adapter SHALL pass user message content only as entries of the message list with the role value `user` and SHALL exclude user message content from the system instruction text.

### Requirement 12: Conversation Context and Memory

**User Story:** As a user, I want the assistant to remember the current conversation, so that follow-up questions build on earlier turns without mixing in other conversations.

Provenance: [User-directed]; [New proposed requirement] relative to the Epic 04 backlog, which does not cover memory.

#### Acceptance Criteria

1. THE Conversation_Store SHALL key every conversation by the pair of the fixed user identifier `DEMO` and the `conversation_id`.
2. WHEN a chat turn terminates, THE Conversation_Store SHALL retain exactly one turn record for that turn containing the user message text, the answer text returned to the client, the HSE scope decision, the classified intent, the resolved structured analytics intent when the turn produced one, the request timestamp and the turn completion timestamp, with both timestamps expressed in ISO 8601 UTC.
3. WHEN a request supplies a `conversation_id` that THE Conversation_Store holds, THE Conversation_Store SHALL supply the retained turn records of that `conversation_id` as context for the turn ordered chronologically by request timestamp, oldest record first.
4. WHEN a request supplies a `conversation_id` that THE Conversation_Store does not hold, including a value that THE Chat_Endpoint never issued, THE Conversation_Store SHALL create a new conversation record for that `conversation_id`, supply an empty context for the turn, and return no error.
5. WHEN THE Conversation_Store creates a conversation record for a `conversation_id` supplied by the request, THE Chat_Endpoint SHALL respond with the same `conversation_id` value that the request supplied.
6. THE Conversation_Store SHALL supply context for exactly one `conversation_id` per turn.
7. THE Conversation_Store SHALL exclude turns belonging to one `conversation_id` from the context supplied for a different `conversation_id`.
8. THE Conversation_Store SHALL support concurrent conversations for the `DEMO` user, each isolated by its own `conversation_id`.
9. THE Conversation_Store SHALL retain at most a configured maximum number of turns per conversation.
10. THE Config_Loader SHALL expose the per-conversation turn maximum as configuration with a default value of `10` turns.
11. WHEN a conversation exceeds the per-conversation turn maximum, THE Conversation_Store SHALL discard the oldest retained turns of that conversation until the retained turn count equals the maximum.
12. THE Conversation_Store SHALL retain at most a configured maximum number of conversations.
13. THE Config_Loader SHALL expose the conversation maximum as configuration with a default value of `100` conversations.
14. WHEN the retained conversation count exceeds the conversation maximum, THE Conversation_Store SHALL evict conversations in ascending order of their last access timestamp, where the last access timestamp is set both when context is supplied for a conversation and when a turn record is appended to it, until the retained conversation count equals the maximum.
15. THE Conversation_Store SHALL measure the expiry of a conversation from the completion timestamp of the most recent turn record retained for that conversation, SHALL treat the conversation as expired once the configured time-to-live has elapsed from that timestamp, and SHALL leave that timestamp unchanged when supplying context for a turn.
16. THE Config_Loader SHALL expose the conversation time-to-live as configuration with a default value of `1800` seconds.
17. WHEN a request supplies a `conversation_id` whose conversation has expired, THE Conversation_Store SHALL create a new conversation record for that `conversation_id` and supply an empty context for the turn.
18. THE Conversation_Store SHALL hold conversation records in application memory for this release.
19. THE Conversation_Store SHALL expose a storage interface consisting of the operations `get_context(user_id, conversation_id)` returning the retained turn records of that conversation in chronological order and an empty sequence when the conversation is absent or expired, `append_turn(user_id, conversation_id, turn_record)` returning the retained turn count of that conversation after the append, and `purge_expired()` returning the count of conversations removed; SHALL key every operation by the pair `(user_id, conversation_id)` so that a multi-user implementation requires no interface change; SHALL define `append_turn` as non-idempotent by retaining one additional turn record per call; and SHALL define `get_context` and `purge_expired` as idempotent by returning equal results for repeated calls that are not separated by an `append_turn` call and by changing no retained turn record content.
20. WHEN THE LLM_API starts a new execution environment, THE Conversation_Store SHALL start with zero retained conversations.
21. THE Chat_Endpoint SHALL document in its OpenAPI description that conversation context is best-effort, is held per execution environment, and is lost when an execution environment is replaced.
22. THE Conversation_Store SHALL exclude credential values, connection strings and system prompt text from retained turns.
23. THE Conversation_Store SHALL exclude generated SQL statement text, executed SQL statement text, supplied schema context text, warehouse result set rows, free-text incident narrative content and employee personally identifiable information from every retained turn record.
24. WHEN THE Conversation_Store supplies context for a turn, THE Conversation_Store SHALL exclude the turn record of that same turn from the supplied context.
25. WHEN THE Intent_Classifier processes a message that omits the measure, the filters or the time range and refers to a preceding turn, THE Intent_Classifier SHALL resolve the omitted elements from the retained analytics intent of the most recent retained turn of that `conversation_id` whose intent is `DATA_QUERY`.
26. THE Conversation_Store SHALL retain the resolved analytics intent of a turn as a serialized value of at most `2000` characters.
27. IF the serialized analytics intent of a turn exceeds `2000` characters, or the assembled turn record exceeds the per-turn character budget, THEN THE Conversation_Store SHALL retain the turn record with the analytics intent omitted and with every other field of criterion 2 retained.
28. THE Conversation_Store SHALL limit each retained turn record to a per-turn character budget of `5000` characters, counted across every retained field of that record.
29. IF a turn record exceeds `5000` characters after the analytics intent has been omitted, THEN THE Conversation_Store SHALL truncate the retained user message text so that the retained record is `5000` characters and SHALL retain the answer text, the HSE scope decision, the classified intent and both timestamps unchanged.
30. THE Config_Loader SHALL expose the total conversation-store character budget as configuration with a default value of `5000000` characters.
31. WHEN the total retained character count across all conversations exceeds the total conversation-store character budget, THE Conversation_Store SHALL evict conversations in ascending order of their last access timestamp until the total is at or below the budget, and SHALL discard the oldest retained turns of the last remaining conversation until the total is at or below the budget when no other conversation remains.
32. WHEN THE Conversation_Store appends a turn record, THE Conversation_Store SHALL apply its bounding rules in the order expiry of time-to-live-elapsed conversations first, per-conversation turn-maximum trimming of the appended-to conversation second, conversation-maximum least-recently-used eviction third, and total-character-budget least-recently-used eviction fourth.
33. WHEN THE Conversation_Store supplies context for a turn, THE Conversation_Store SHALL set the last access timestamp of that conversation to the request timestamp of that turn.
34. WHEN THE Conversation_Store creates a conversation record for a `conversation_id` whose previous conversation expired, THE Chat_Endpoint SHALL respond with HTTP status `200`, SHALL respond with the same `conversation_id` value that the request supplied, and SHALL omit from the response body any field reporting expiry or recreation, so that the recreation is observable to the client only as absent conversation context.
35. WHEN two chat turns for the same `conversation_id` are processed concurrently in one execution environment, THE Conversation_Store SHALL serialize the append operations for that `conversation_id` so that both turn records are retained, no retained turn record is partially written, and the bounds of criteria 9, 12, 28 and 30 hold after both appends complete.
36. THE LLM_API SHALL document that, because the MVP carries no endpoint authentication, any client that supplies a `conversation_id` held by THE Conversation_Store receives the retained context of that conversation, and SHALL record this as an accepted limitation cross-referencing the documented no-authentication deployment risk of Requirement 13.
37. THE Config_Loader SHALL expose the conversation storage backend as configuration with a default value of `memory`, so that an alternative implementation of the criterion 19 interface is selected without changing THE Agent_Orchestrator or THE Chat_Endpoint.
38. WHEN THE Conversation_Store supplies context for a turn, THE Request_Logger SHALL include the count of retained turn records supplied as context in the request log entry.

### Requirement 13: Security

**User Story:** As a Security Architect, I want defence in depth around secrets, network exposure and model output, so that a single defect does not compromise the warehouse or leak credentials.

Provenance: [Notion-confirmed: Project Description §10.2 security non-negotiables] reconciled with the [User-directed] exclusion of authentication from this MVP; see §Risks R-3 and §Open Questions OQ-7.

#### Acceptance Criteria

1. THE LLM_API SHALL resolve every secret value from AWS SSM Parameter Store or AWS Secrets Manager at execution-environment initialization, and SHALL exclude every secret value from its source code, its container image layers and its deployment artifact.
2. THE LLM_API SHALL exclude secret values, database connection strings, model-provider API keys and environment-file contents from every version-controlled file of the repository.
3. THE Config_Loader SHALL read every non-secret configuration value from environment variables and SHALL reject startup when a required non-secret variable is absent.
4. IF a required configuration value is absent at startup, THEN THE LLM_API SHALL respond to the `GET /health` route with HTTP status `200` and a body reporting a failed status that names the absent configuration key, and SHALL exclude the value of every secret from that body.
5. THE LLM_API SHALL evaluate every rule of Requirement 6 and every session control of Requirement 7 in components that issue zero model-provider calls while reaching their verdict.
6. IF THE SQL_Generator produces a SQL statement that violates any rule of Requirement 6, THEN THE Query_Firewall SHALL reject the statement irrespective of any instruction contained in the user message, in a retained conversation turn or in the model output.
7. WHEN a chat request is received, THE Chat_Endpoint SHALL validate every request-body field against its declared type and length bound before THE Agent_Orchestrator processes the request, and SHALL exclude every request-body field other than `message` and `conversation_id` from the agent state.
8. WHEN a user message contains text that resembles a configuration directive, THE Agent_Orchestrator SHALL process the text as message content only and SHALL leave every configured constraint value unchanged for that turn.
9. WHEN a chat request fails, THE Chat_Endpoint SHALL respond with a body that excludes stack traces, exception class names, SQL statement text, schema names, table names, column names, host names, file system paths and credential values.
10. THE Chat_Endpoint SHALL restrict cross-origin requests to the origin values named in configuration, and SHALL permit only the HTTP methods `POST`, `GET` and `OPTIONS` and only the request headers `Content-Type` and `Authorization`.
11. THE Config_Loader SHALL read the allowed cross-origin origin values from environment configuration as an explicit list with a default value of an empty list.
12. THE LLM_API SHALL accept endpoint authentication as request middleware that can be added without changing any field name, field type or HTTP status code of the contract stated in Requirement 1.
13. THE LLM_API SHALL document that this release deploys no endpoint authentication, no authorization and no RBAC, that public exposure without an authentication layer is an accepted deployment risk, and that the deployment decision recorded as OQ-7 is unresolved.
14. THE Query_Executor SHALL send every user-supplied literal value to the warehouse as a bound query parameter, and SHALL send every identifier only after that identifier is matched against the approved schema allow-list.
15. THE LLM_API SHALL exclude every capability that writes to the warehouse, to object storage, to a message queue, to a file system location outside the runtime temporary directory, or to any other data store.
16. THE LLM_API SHALL document as an exposure of the unauthenticated deployment that any caller reaching the `POST /chat/message` route may supply any `conversation_id` value and receive an answer informed by the turns retained under that `conversation_id`, bounded by the conversation time-to-live of `1800` seconds and the per-conversation turn maximum of `10` turns of Requirement 12.
17. THE Chat_Endpoint SHALL generate every `conversation_id` value it creates with at least `128` bits of randomness, so that a caller cannot enumerate the `conversation_id` values of other conversations.
18. THE LLM_API SHALL document as an exposure of the unauthenticated deployment that any caller reaching the `POST /chat/message` route may consume model-provider budget, bounded by the per-turn model-call maximum of `4` calls of Requirement 10, the configured maximum output tokens of Requirement 11, the configured request rate limit and the configured concurrent-request bound.
19. THE LLM_API SHALL document as an exposure of the unauthenticated deployment that any caller reaching the `POST /chat/message` route may issue warehouse load, bounded by the statement timeout of `10000` milliseconds and the row cap of `1000` rows of Requirement 7, the configured request rate limit and the configured concurrent-request bound.
20. IF the count of chat requests received from one source IP address within a `60`-second window exceeds the configured request rate limit, THEN THE Chat_Endpoint SHALL respond with HTTP status `429` and a body stating that the request rate limit was exceeded, and THE Agent_Orchestrator SHALL issue zero model-provider calls and zero warehouse queries for that request.
21. IF the count of in-flight chat requests equals the configured concurrent-request bound when a chat request is received, THEN THE Chat_Endpoint SHALL respond with HTTP status `429` and a body stating that the service is at capacity, and THE Agent_Orchestrator SHALL issue zero model-provider calls and zero warehouse queries for that request.
22. THE Config_Loader SHALL expose the request rate limit as configuration with a default value of `60` requests per `60` seconds per source IP address, and the concurrent-request bound as configuration with a default value of `10` in-flight chat requests.
23. THE LLM_API SHALL implement the HSE scope decision of THE Scope_Guard, the verdict of THE Query_Firewall, the privilege set of the `llm_read` role and the read-only transaction of THE Query_Executor as four controls, each of which prevents data modification without depending on the other three.
24. IF exactly one of the four controls named in criterion 23 is disabled, THEN THE LLM_API SHALL execute zero statements that insert, update, delete or alter warehouse data.
25. THE Agent_Orchestrator SHALL supply user message text to THE Model_Provider_Adapter only as user-role message content, and SHALL exclude user message text from the system instruction content of every provider call.
26. THE Agent_Orchestrator SHALL supply retained conversation turns to THE Model_Provider_Adapter only as prior-turn message content, and SHALL exclude retained turn text from the system instruction content of every provider call.
27. IF a retained conversation turn contains text directing THE Agent_Orchestrator to disregard its configured constraints, THEN THE Scope_Guard SHALL produce the same HSE scope decision for the current message as it produces for that message with an empty conversation context, and THE Query_Firewall SHALL apply every rule of Requirement 6 unchanged.
28. WHEN THE Answer_Synthesizer includes a warehouse-returned text value in an answer, THE Answer_Synthesizer SHALL supply that value as data content only, SHALL emit it as markdown text, and SHALL truncate it to at most `200` characters.
29. THE Config_Loader SHALL classify as secret values the `llm_read` database user name, the `llm_read` database password, the warehouse host and port connection settings, and the model-provider credential, and SHALL classify every other configuration value as non-secret.
30. THE LLM_API SHALL hold resolved secret values in process memory only, and SHALL exclude every secret value from files written to disk, from log entries, from response bodies, from exception messages and from the published OpenAPI schema.
31. THE LLM_API SHALL exclude environment files matching the patterns `.env` and `.env.*` from version control through the repository ignore configuration, and SHALL fail the CI pipeline when a tracked file matches those patterns or when a tracked file contains a value matching a credential pattern.
32. WHEN a chat request fails, THE Chat_Endpoint SHALL respond with a body whose fields are limited to the error category of Requirement 14, a message text fixed per error category, and the request identifier, so that two failures sharing one error category produce responses differing only in the request identifier.
33. WHERE the configured environment value is `production`, IF the allowed cross-origin origin list contains the wildcard value `*`, THEN THE Config_Loader SHALL fail configuration validation at startup and THE LLM_API SHALL report a failed status on the `GET /health` route naming the cross-origin configuration key.
34. IF a request body exceeds `16384` bytes, THEN THE Chat_Endpoint SHALL reject the request with HTTP status `413` and a body stating the maximum supported request body size, and THE Config_Loader SHALL expose the request body size cap as configuration with a default value of `16384` bytes.
35. THE LLM_API SHALL accept inbound HTTP traffic over TLS version `1.2` or higher only, and SHALL open the warehouse connection and every model-provider connection over TLS version `1.2` or higher only.
36. THE LLM_API SHALL exclude code paths that execute an operating-system shell command, that read a file outside its deployment artifact and its runtime temporary directory, or that open an outbound network connection to a host other than the configured model-provider endpoint, the configured warehouse host and AWS service endpoints.
37. THE LLM_API SHALL pin every runtime dependency to an exact resolved version in `uv.lock`, and SHALL fail the CI pipeline when the committed lock file does not match `pyproject.toml`.

### Requirement 14: Logging

**User Story:** As an operator, I want one log entry per request describing the outcome, so that I can diagnose failures without exposing sensitive data.

Provenance: [User-directed]; [New proposed requirement] relative to the Epic 04 backlog.

#### Acceptance Criteria

1. WHEN a chat request reaches a terminal path, including a successful answer, a clarification response, a scope rejection, a firewall rejection, a request-validation failure, a turn timeout, a provider failure, a warehouse failure and an unhandled exception, THE Request_Logger SHALL emit exactly one log entry for that request, irrespective of whether the responded HTTP status is in the `2xx`, `4xx` or `5xx` range.
2. THE Request_Logger SHALL include a `request_id` field of JSON type string in every request log entry, whose value equals the `request_id` value returned in the response body for that request.
3. THE Request_Logger SHALL include a `conversation_id` field of JSON type string in every request log entry, whose value equals the `conversation_id` value returned in the response body for that request.
4. THE Request_Logger SHALL include a `user_id` field of JSON type string in every request log entry, whose value is the literal `DEMO`.
5. THE Request_Logger SHALL include a `timestamp` field of JSON type string in every request log entry, expressed as an ISO 8601 UTC instant with millisecond precision.
6. THE Request_Logger SHALL include a `turn_outcome` field of JSON type string in every request log entry, whose value equals the agent workflow outcome recorded by THE Agent_Orchestrator for that turn and is restricted to the enumerated set of Requirement 10 acceptance criterion 33.
7. THE Request_Logger SHALL include a `scope_decision` field of JSON type string in every request log entry, restricted to one of the values `IN_SCOPE`, `OUT_OF_SCOPE` or `UNSAFE`, whose value equals the HSE scope decision recorded by THE Scope_Guard for that turn.
8. THE Request_Logger SHALL include an `intent` field of JSON type string in every request log entry, restricted to one of the values `DATA_QUERY`, `GENERAL_CHAT`, `CLARIFICATION_NEEDED`, `REJECTED` or `NOT_CLASSIFIED`, where `NOT_CLASSIFIED` denotes a turn that terminated before THE Intent_Classifier produced a classification.
9. THE Request_Logger SHALL include a `query_outcome` field of JSON type string in every request log entry, restricted to one of the values `NOT_EXECUTED`, `SUCCESS`, `TIMEOUT` or `ERROR`, and WHERE the `query_outcome` value is not `NOT_EXECUTED`, THE Request_Logger SHALL include a `query_duration_ms` field of JSON type integer holding the query execution duration in milliseconds as recorded by THE Query_Executor.
10. WHERE a turn ended in an error condition or in a rejection, THE Request_Logger SHALL include an `error_category` field of JSON type string in the request log entry, and WHERE a turn ended with an answer or a clarification response, THE Request_Logger SHALL omit the `error_category` field.
11. THE Request_Logger SHALL restrict the `error_category` value to one of `VALIDATION_ERROR`, `SCOPE_REJECTED`, `FIREWALL_REJECTED`, `INTENT_UNRESOLVED`, `PROVIDER_ERROR`, `WAREHOUSE_ERROR`, `TIMEOUT` or `INTERNAL_ERROR`.
12. THE Request_Logger SHALL exclude secret values, access tokens, database credentials and connection strings from every log entry.
13. THE Request_Logger SHALL exclude system prompt text and hidden prompt text from every log entry.
14. THE Request_Logger SHALL exclude free-text incident narrative content and every warehouse result set value from every log entry, and SHALL limit reported result information to the `result_row_count` and `result_truncated` fields.
15. THE Request_Logger SHALL exclude employee personally identifiable information from every log entry, including person names, national identity numbers, e-mail addresses and telephone numbers.
16. THE Request_Logger SHALL emit every log entry to standard output as a single JSON object serialized on one line containing zero unescaped line-feed characters and zero unescaped carriage-return characters, so that AWS CloudWatch captures one entry as one event.
17. THE Config_Loader SHALL expose the log level as configuration restricted to the values `DEBUG`, `INFO`, `WARNING` and `ERROR`, with the default value `INFO`.
18. WHERE the log level is set to `DEBUG`, THE Request_Logger SHALL include a `query_executed` field of JSON type string holding the executed SQL statement in the request log entry.
19. WHERE the log level is set to `INFO`, `WARNING` or `ERROR`, THE Request_Logger SHALL omit the `query_executed` field from the request log entry.
20. WHERE a turn attempted to acquire a warehouse connection, THE Request_Logger SHALL include a `connection_acquisition_ms` field of JSON type integer holding the elapsed milliseconds between the start of the connection attempt and its completion.
21. WHERE the `query_outcome` value is `SUCCESS`, THE Request_Logger SHALL include a `result_row_count` field of JSON type integer holding the number of rows returned to THE Answer_Synthesizer and a `result_truncated` field of JSON type boolean whose value is `true` when the returned row count equals the configured row cap and `false` otherwise.
22. WHERE THE Query_Firewall reached a verdict for a turn, THE Request_Logger SHALL include a `firewall_verdict` field of JSON type string restricted to the values `ADMITTED` or `REJECTED`, and WHERE the `firewall_verdict` value is `REJECTED`, THE Request_Logger SHALL include a `firewall_reason_code` field of JSON type string restricted to the enumerated rejection reason code set of Requirement 6 acceptance criterion 41.
23. THE Request_Logger SHALL include a `model_call_count` field of JSON type integer in every request log entry, holding a value between `0` and the configured per-turn model-call maximum inclusive.
24. WHERE the `model_call_count` value is `1` or greater, THE Request_Logger SHALL include a `prompt_tokens` field of JSON type integer and a `completion_tokens` field of JSON type integer holding the summed token counts recorded by THE Model_Provider_Adapter for the turn, and a `prompt_version` field of JSON type string holding the identifier of the prompt set used for the turn.
25. THE Request_Logger SHALL include a `total_duration_ms` field of JSON type integer in every request log entry, holding the elapsed milliseconds between receipt of the request by THE Chat_Endpoint and determination of the response outcome.
26. THE Request_Logger SHALL include in every request log entry a `service` field of JSON type string holding the literal value `kognit-ai-hse-llm-api`, a `service_version` field of JSON type string holding the configured release identifier, an `environment` field of JSON type string restricted to the values `local`, `dev`, `staging` or `prod`, a `cold_start` field of JSON type boolean whose value is `true` for the first request served by an execution environment and `false` for every later request served by that execution environment, and, WHERE the service runs as an AWS Lambda invocation, a `lambda_request_id` field of JSON type string holding the AWS Lambda request identifier.
27. THE Request_Logger SHALL emit the request log entry after the response outcome for that request is determined, and SHALL increase the total response time of the request by at most `50` milliseconds.
28. IF serialization or emission of a request log entry fails, THEN THE LLM_API SHALL return the response already determined for that request with its determined HTTP status, and THE Request_Logger SHALL emit one replacement entry containing only the `request_id`, `timestamp`, `turn_outcome` and `error_category` fields with `error_category` set to `INTERNAL_ERROR`.
29. IF the serialized request log entry exceeds `16384` bytes, THEN THE Request_Logger SHALL truncate every string field value longer than `512` characters to its first `512` characters and SHALL include a `truncated_fields` field of JSON type array of strings naming every truncated field.
30. WHERE the log level is set to `INFO`, `WARNING` or `ERROR`, THE Request_Logger SHALL exclude the user message text from the request log entry and SHALL instead include a `message_length` field of JSON type integer holding the character count of the submitted message and a `message_language` field of JSON type string holding a two-letter language code or the literal value `unknown`.
31. WHERE the log level is set to `DEBUG`, THE Request_Logger SHALL include a `message` field of JSON type string holding the submitted user message text after the redaction pass.
32. THE Request_Logger SHALL apply a redaction pass to every string field value before emission that replaces with the literal value `[REDACTED]` every substring that equals a configured secret value, every substring matching a database connection-string shape carrying a user name and password, every substring preceded by the token `Bearer`, and every contiguous substring of `32` or more characters drawn solely from the hexadecimal or base64 alphabets.
33. WHERE a turn ended in an unhandled exception, THE Request_Logger SHALL emit the request log entry at level `ERROR` with `error_category` set to `INTERNAL_ERROR` and SHALL include an `exception_type` field of JSON type string holding the exception class name, and WHERE the log level is additionally set to `DEBUG`, THE Request_Logger SHALL include a `stack_trace` field of JSON type string holding the redacted stack trace.
34. WHEN a request carries a correlation header whose value length is between `1` and `128` characters inclusive, THE Request_Logger SHALL set the `correlation_id` field of JSON type string in the request log entry to that header value.
35. IF a request carries no correlation header, or carries a correlation header whose value length is `0` or exceeds `128` characters, THEN THE Chat_Endpoint SHALL generate a correlation identifier for the request, THE Request_Logger SHALL set the `correlation_id` field to the generated value, and THE Chat_Endpoint SHALL return the `correlation_id` value in a response header.
36. IF the resolved log level is `DEBUG` while the resolved environment value is `prod`, THEN THE Config_Loader SHALL fail configuration validation at startup and THE LLM_API SHALL report a failed status on the `GET /health` route naming the log-level configuration key.
37. WHEN the `GET /health` route is called, THE Request_Logger SHALL emit no request log entry for that call.
38. THE Request_Logger SHALL exclude from every request log entry every field name other than `request_id`, `correlation_id`, `conversation_id`, `user_id`, `timestamp`, `turn_outcome`, `scope_decision`, `intent`, `context_turn_count`, `message_length`, `message_language`, `message`, `query_outcome`, `query_duration_ms`, `connection_acquisition_ms`, `result_row_count`, `result_truncated`, `firewall_verdict`, `firewall_reason_code`, `model_call_count`, `prompt_tokens`, `completion_tokens`, `prompt_version`, `error_category`, `exception_type`, `stack_trace`, `query_executed`, `total_duration_ms`, the per-stage duration fields of Requirement 16 acceptance criterion 17, `service`, `service_version`, `environment`, `lambda_request_id`, `cold_start` and `truncated_fields`, and THE LLM_API SHALL exclude centralized log aggregation, distributed tracing, monitoring dashboards, query auditing and model observability from this release as recorded in §Future Work.

### Requirement 15: Configuration, Packaging and Local Execution

**User Story:** As a Developer, I want the service configurable by environment and runnable locally in Docker, so that I can develop and verify behaviour without AWS access.

Provenance: [Repo-confirmed] current UV, Ruff, `build.sh` and Lambda setup; [Notion-confirmed: CI/CD Pipelines] for the pipeline steps; the Docker requirement is [User-directed] [New proposed requirement]; see §Risks R-6, R-13 and §Open Questions OQ-17, OQ-18, OQ-21.

#### Configuration Variables

Every variable carries the prefix `KOGNIT_LLM_`. "Required" means startup validation fails when the variable is absent. "Chat-critical" and "Degrading" classify the absence consequence per AC 19 and AC 20.

| Variable | Type | Required | Default | Class | Bound to |
|---|---|---|---|---|---|
| `KOGNIT_LLM_ENVIRONMENT` | enum `local`, `ci`, `aws` | No | `local` | Chat-critical | AC 6 |
| `KOGNIT_LLM_AWS_REGION` | string | No | `us-east-1` | Degrading | R7.8 |
| `KOGNIT_LLM_PORT` | integer `1024`–`65535` | No | `8000` | Chat-critical | AC 8 |
| `KOGNIT_LLM_LOG_LEVEL` | enum `DEBUG`, `INFO`, `WARNING`, `ERROR` | No | `INFO` | Degrading | R14.17 |
| `KOGNIT_LLM_CORS_ORIGINS` | comma-separated string list | No | empty list | Degrading | R13.10–R13.11 |
| `KOGNIT_LLM_EXPOSE_EXECUTED_SQL` | boolean | No | `false` | Degrading | R1.12–R1.14 |
| `KOGNIT_LLM_MESSAGE_MAX_CHARS` | integer `1`–`8000` | No | `2000` | Chat-critical | R1.5 |
| `KOGNIT_LLM_ANSWER_MAX_CHARS` | integer `1`–`2000` | No | `600` | Chat-critical | R9.4 |
| `KOGNIT_LLM_ANSWER_LANGUAGE` | enum `auto`, `es`, `en` | No | `auto` | Chat-critical | R9.6–R9.7 |
| `KOGNIT_LLM_REFERENCE_TIMEZONE` | IANA timezone name | No | `America/Bogota` | Chat-critical | R3.9 |
| `KOGNIT_LLM_FIRST_DAY_OF_WEEK` | enum `MONDAY`, `SUNDAY` | No | `MONDAY` | Chat-critical | R3.32 |
| `KOGNIT_LLM_DEFAULT_LOOKBACK_DAYS` | integer `1`–`3650` | No | `365` | Chat-critical | R3.45 |
| `KOGNIT_LLM_INTENT_CONFIDENCE_THRESHOLD` | decimal `0.00`–`1.00` | No | `0.60` | Chat-critical | R3.24 |
| `KOGNIT_LLM_DB_HOST` | string | Yes when `KOGNIT_LLM_ENVIRONMENT` is `aws` | none | Degrading | R7.9 |
| `KOGNIT_LLM_DB_PORT` | integer `1`–`65535` | No | `5432` | Degrading | R7.9 |
| `KOGNIT_LLM_DB_NAME` | string | Yes when `KOGNIT_LLM_ENVIRONMENT` is `aws` | none | Degrading | R7.9 |
| `KOGNIT_LLM_DB_SCHEMA` | string | No | `public` | Degrading | R6.9 |
| `KOGNIT_LLM_DB_ROLE` | string | No | `llm_read` | Degrading | R7.1 |
| `KOGNIT_LLM_DB_SSLMODE` | enum `require`, `verify-full`, `disable` | No | `require` | Degrading | R7.20 |
| `KOGNIT_LLM_DB_USER_PARAM` | string, secret-store parameter name | No | `/kognit/db/LLM_READ_USER` | Degrading | A-14, R7.9 |
| `KOGNIT_LLM_DB_PASSWORD_PARAM` | string, secret-store parameter name | No | `/kognit/db/LLM_READ_PASSWORD` | Degrading | A-14, R7.9 |
| `KOGNIT_LLM_DB_USER` | string, local development only | No | none | Degrading | AC 21 |
| `KOGNIT_LLM_DB_PASSWORD` | secret string, local development only | No | none | Degrading | AC 21 |
| `KOGNIT_LLM_DB_CONNECT_TIMEOUT_MS` | integer `100`–`30000` | No | `2000` | Degrading | R7.24 |
| `KOGNIT_LLM_DB_STATEMENT_TIMEOUT_MS` | integer `1000`–`60000` | No | `10000` | Degrading | R7.5 |
| `KOGNIT_LLM_DB_POOL_MAX` | integer `1`–`10` | No | `2` | Degrading | R7.23 |
| `KOGNIT_LLM_DB_POOL_MIN` | integer `0`–`10` | No | `1` | Degrading | R7.23 |
| `KOGNIT_LLM_ROW_CAP` | integer `1`–`10000` | No | `1000` | Chat-critical | R6.14 |
| `KOGNIT_LLM_MAX_RESULT_COLUMNS` | integer `1`–`200` | No | `50` | Chat-critical | R7.33 |
| `KOGNIT_LLM_MAX_RESULT_BYTES` | integer `1024`–`16777216` | No | `1048576` | Chat-critical | R7.33 |
| `KOGNIT_LLM_MAX_RANKING_SIZE` | integer `1`–`100` | No | `25` | Chat-critical | R8.33 |
| `KOGNIT_LLM_MODEL_PROVIDER` | enum `stub`, `openai_compatible`, `bedrock` | No | `stub` | Chat-critical | R11.3, R11.30 |
| `KOGNIT_LLM_MODEL_ID` | string | Yes when `KOGNIT_LLM_MODEL_PROVIDER` is not `stub` | none | Chat-critical | R11.3 |
| `KOGNIT_LLM_MODEL_ENDPOINT` | string | No | none | Chat-critical | R11.3 |
| `KOGNIT_LLM_MODEL_CREDENTIAL_PARAM` | string, secret-store parameter name | Yes when `KOGNIT_LLM_MODEL_PROVIDER` is `openai_compatible` and `KOGNIT_LLM_MODEL_API_KEY` is absent | none | Chat-critical | R11.4 |
| `KOGNIT_LLM_MODEL_API_KEY` | secret string, local development only | No | none | Chat-critical | AC 21 |
| `KOGNIT_LLM_MODEL_TIMEOUT_MS` | integer `1000`–`60000` | No | `15000` | Chat-critical | R11.9 |
| `KOGNIT_LLM_MODEL_TEMPERATURE` | decimal `0.0`–`2.0` | No | `0.0` | Chat-critical | R11.14 |
| `KOGNIT_LLM_MODEL_MAX_OUTPUT_TOKENS` | integer `256`–`8192` | No | `1024` | Chat-critical | R11.14 |
| `KOGNIT_LLM_MODEL_MAX_RETRIES` | integer `0`–`5` | No | `2` | Chat-critical | R11.6 |
| `KOGNIT_LLM_MODEL_CALLS_PER_TURN_MAX` | integer `1`–`10` | No | `4` | Chat-critical | R10.6 |
| `KOGNIT_LLM_TURN_TOKEN_CEILING` | integer `1000`–`200000` | No | `12000` | Chat-critical | R11.28 |
| `KOGNIT_LLM_PROMPT_VERSION` | string | No | `v1` | Chat-critical | R11.3, R14.24 |
| `KOGNIT_LLM_TURN_TIMEOUT_MS` | integer `1000`–`29000` | No | `25000` | Chat-critical | R10.10, R10.28 |
| `KOGNIT_LLM_SCHEMA_CONTEXT_TOKEN_BUDGET` | integer `500`–`32000` | No | `4000` | Chat-critical | R4.10 |
| `KOGNIT_LLM_INCLUDE_DIMENSION_VALUES` | boolean | No | `true` | Degrading | R4.28 |
| `KOGNIT_LLM_DIMENSION_VALUE_MAX` | integer `1`–`500` | No | `50` | Degrading | R4.28 |
| `KOGNIT_LLM_SCHEMA_CACHE_TTL_SECONDS` | integer `0`–`86400` | No | `3600` | Degrading | R4.33 |
| `KOGNIT_LLM_MAX_STATEMENT_CHARS` | integer `100`–`20000` | No | `4000` | Chat-critical | R6.37 |
| `KOGNIT_LLM_MAX_JOIN_COUNT` | integer `1`–`20` | No | `8` | Chat-critical | R6.37 |
| `KOGNIT_LLM_MAX_SUBQUERY_DEPTH` | integer `1`–`10` | No | `3` | Chat-critical | R6.37 |
| `KOGNIT_LLM_MAX_SET_OPERATION_ARMS` | integer `1`–`10` | No | `3` | Chat-critical | R6.37 |
| `KOGNIT_LLM_INLINE_GROUP_ROWS_MAX` | integer `1`–`20` | No | `5` | Chat-critical | R9.25 |
| `KOGNIT_LLM_CONVERSATION_STORE` | enum `memory` | No | `memory` | Chat-critical | R12.37 |
| `KOGNIT_LLM_CONVERSATION_TURN_MAX` | integer `1`–`100` | No | `10` | Chat-critical | R12.10 |
| `KOGNIT_LLM_CONVERSATION_MAX` | integer `1`–`10000` | No | `100` | Chat-critical | R12.13 |
| `KOGNIT_LLM_CONVERSATION_TTL_SECONDS` | integer `60`–`86400` | No | `1800` | Chat-critical | R12.16 |
| `KOGNIT_LLM_CONVERSATION_CHAR_BUDGET` | integer `100000`–`100000000` | No | `5000000` | Chat-critical | R12.30 |
| `KOGNIT_LLM_REQUEST_BODY_MAX_BYTES` | integer `1024`–`1048576` | No | `16384` | Chat-critical | R13.34 |
| `KOGNIT_LLM_RATE_LIMIT_PER_MINUTE` | integer `1`–`10000` | No | `60` | Degrading | R13.22 |
| `KOGNIT_LLM_CONCURRENT_REQUEST_MAX` | integer `1`–`100` | No | `10` | Degrading | R13.22 |
| `KOGNIT_LLM_SERVICE_VERSION` | string | No | `0.1.0` | Degrading | R14.26 |

#### Acceptance Criteria

1. THE LLM_API SHALL target Python `3.13` as declared by the repository `.python-version` file and by the `requires-python` constraint in `pyproject.toml`.
2. THE LLM_API SHALL declare every runtime dependency in `pyproject.toml` and SHALL pin the resolved versions in `uv.lock`.
3. THE LLM_API SHALL pass `uv lock --check` with the committed lock file.
4. THE LLM_API SHALL pass `ruff check` at Ruff version `0.15.0` with the repository configuration of line length `88`, target version `py313` and rule selection `E`, `F`, `I`, `B`, `UP`, reporting zero violations.
5. THE LLM_API SHALL pass `ty check` at Ty version `0.0.29` with zero reported violations.
6. THE Config_Loader SHALL read every variable named in the Configuration Variables table from environment variables and SHALL apply the tabled default value when an optional variable is absent.
7. THE Config_Loader SHALL validate every variable named in the Configuration Variables table through exactly one Pydantic settings model, and SHALL construct that model exactly once per execution environment.
8. THE LLM_API SHALL provide a Dockerfile that builds an image based on a Python `3.13` runtime, exposes the port given by `KOGNIT_LLM_PORT`, and runs the service process as a non-root user whose user identifier is not `0`.
9. THE LLM_API SHALL provide a Docker Compose definition that supplies every variable named in the Configuration Variables table to the service container through environment variables and declares no secret value inline.
10. WHEN the service runs from the Docker image with `KOGNIT_LLM_MODEL_PROVIDER` set to `stub` and the remaining required variables set, THE LLM_API SHALL serve the `POST /chat/message` route and the `GET /health` route on the port given by `KOGNIT_LLM_PORT`.
11. THE LLM_API SHALL document in the repository README every variable named in the Configuration Variables table together with its type, its required condition and its default value.
12. THE LLM_API SHALL produce a deployment artifact whose installed distribution set equals the non-development distribution set resolved by `uv.lock`, including every distribution required by the LangGraph workflow and the Model_Provider_Adapter.
13. THE LLM_API SHALL produce a deployment artifact whose uncompressed size is at most `250` megabytes and whose compressed archive size is at most `50` megabytes.
14. THE LLM_API SHALL retain a Mangum-based AWS Lambda entry point constructed with the API Gateway base path `/llm`, exposed as a module-level callable named `handler`.
15. WHEN the CD pipeline invokes the published Lambda version with the `tests/events/health-check.json` payload, whose `rawPath` and `routeKey` name the `GET /health` route, THE LLM_API SHALL respond with `statusCode` equal to `200`.
16. THE Config_Loader SHALL resolve a complete configuration without reading the environment variable `is_in_aws_lambda`, so that configuration resolution is identical in the local, CI and AWS environments.
17. THE Config_Loader SHALL perform zero network calls and zero secret-store calls while its module is being imported, and SHALL defer every such call to an explicit initialization call or to first use.
18. IF one or more variables named in the Configuration Variables table are absent when required or hold a value outside their tabled type or range, THEN THE Config_Loader SHALL raise exactly one validation error at startup that names every offending variable in a single report and excludes every secret value.
19. IF a variable classified as Chat-critical in the Configuration Variables table is absent when required or invalid, THEN THE Chat_Endpoint SHALL respond to `POST /chat/message` with HTTP status `503` and a body stating that the assistant is unavailable, and THE LLM_API SHALL continue to serve `GET /health` with HTTP status `200` and a failed status for the affected dependency.
20. IF a variable classified as Degrading in the Configuration Variables table is absent or invalid, THEN THE LLM_API SHALL serve `POST /chat/message` for `GENERAL_CHAT` turns and SHALL report a failed status for the affected dependency on `GET /health`.
21. WHERE an environment variable supplies a secret value directly, THE Config_Loader SHALL use that value and SHALL issue no AWS SSM Parameter Store call and no AWS Secrets Manager call for that secret.
22. IF the environment variable that supplies a secret value directly is absent, THEN THE Config_Loader SHALL resolve the secret from the parameter name given by the corresponding parameter-name variable, attempting AWS SSM Parameter Store first and AWS Secrets Manager second.
23. THE Config_Loader SHALL resolve each secret value at most once per execution environment and SHALL reuse the resolved value for every subsequent request served by that execution environment.
24. IF every configured secret-store lookup for a secret value fails, THEN THE LLM_API SHALL continue serving `GET /health` with HTTP status `200`, SHALL report a failed status for the dependency that the secret serves, and SHALL NOT terminate the service process.
25. THE Config_Loader SHALL support construction of its settings model from an explicit key-value mapping supplied by the caller, without AWS credentials and without network access.
26. WHEN the test suite runs with no AWS credentials present in the environment, THE LLM_API SHALL import every application module and THE Config_Loader SHALL construct a valid configuration.
27. THE LLM_API SHALL resolve its configuration module through an import path that succeeds both when the package root is the repository root and when the package root is the `src` directory, matching the `pythonpath` entries `.` and `src` declared in `pyproject.toml`.
28. THE LLM_API SHALL build a Docker image that contains no secret value, no `.env` file and no credential file.
29. THE LLM_API SHALL declare a container health check that calls the `GET /health` route with an interval of `30` seconds, a timeout of `5` seconds, a start period of `10` seconds and a retry count of `3`.
30. WHERE the Docker Compose definition starts a PostgreSQL container, THE LLM_API SHALL document that container as a local development fixture that contains no warehouse data, and SHALL exclude it from the CI test run and from every deployed environment.
31. WHEN the service starts with `KOGNIT_LLM_ENVIRONMENT` set to `local`, `KOGNIT_LLM_MODEL_PROVIDER` set to `stub`, and no reachable AWS SSM Parameter Store, THE LLM_API SHALL respond to `GET /health` with HTTP status `200`, a warehouse status value and a model-provider status value, and SHALL NOT terminate the service process.
32. THE LLM_API SHALL derive the dependency set installed into the deployment artifact from the committed `uv.lock` file, and SHALL fail the build when the lock file is not in sync with `pyproject.toml`.
33. THE LLM_API SHALL install every native-extension dependency, including `psycopg[binary,pool]`, for the AWS Lambda target platform `x86_64-manylinux2014` and for Python `3.13`, and SHALL NOT install a distribution built for the build runner platform when that platform differs from the target platform.
34. IF the uncompressed artifact size exceeds `250` megabytes or the compressed archive size exceeds `50` megabytes, THEN the build SHALL fail with a message stating the measured size and the exceeded limit.
35. THE LLM_API SHALL document a fallback packaging path of a container image or a Lambda layer, to be applied when the artifact exceeds either limit stated in AC 13.
36. THE LLM_API SHALL set the FastAPI application root path to `/llm` and the Mangum API Gateway base path to `/llm`, so that an API Gateway request path of `/llm/chat/message` reaches the application route `/chat/message`.
37. THE LLM_API SHALL serve the health route for an API Gateway payload whose `rawPath` is `/health` and for an API Gateway payload whose `rawPath` is `/llm/health`, responding with `statusCode` equal to `200` in both cases.
38. THE LLM_API SHALL install dependencies in the CI pipeline and in the CD pipeline from the same committed `uv.lock` file, and SHALL resolve no dependency version outside that lock file during either pipeline.
39. THE LLM_API SHALL include every Python module and every Python subpackage of the `src` directory in the deployment artifact, so that a module placed in a subdirectory of `src` is present in the artifact.
40. WHEN the deployment artifact is built, THE LLM_API SHALL verify that the artifact contains the module that defines the `handler` callable and every module that `handler` imports transitively, and SHALL fail the build when a module is absent.

### Requirement 16: Non-Functional Requirements

**User Story:** As a Product Owner, I want stated performance, reliability and quality targets, so that the service is acceptable in production and verifiable in CI.

Provenance: [Notion-confirmed: Project Description §9 Definition of Done, §CI/CD Pipelines]. Chat latency targets are [Assumption]; the documented Notion targets cover ML inference under 500 ms, BI dashboards under 3 s and ETL under 10 min, and do not cover chat. See §Open Questions OQ-19.

#### Acceptance Criteria

1. WHEN THE LLM_API serves a `DATA_QUERY` turn on a warm execution environment, THE LLM_API SHALL respond within `8000` milliseconds at the 95th percentile of the most recent `100` such turns, measured from request receipt at THE Chat_Endpoint to response emission by THE Chat_Endpoint, as a proposed target pending OQ-19.
2. WHEN THE LLM_API serves a turn whose HSE scope decision is `OUT_OF_SCOPE` or `UNSAFE`, THE LLM_API SHALL respond within `3000` milliseconds at the 95th percentile of the most recent `100` such turns, as a proposed target pending OQ-19.
3. WHEN THE LLM_API serves the first request of a new execution environment, THE LLM_API SHALL respond within `15000` milliseconds, measured from request receipt to response emission, as a proposed target pending OQ-19.
4. THE LLM_API SHALL initialize the model-provider configuration and the warehouse connection settings once per execution environment.
5. THE Query_Executor SHALL bound every warehouse query by the configured statement timeout of Requirement 7.
6. THE Query_Executor SHALL bound every result set by the configured row cap of Requirement 6.
7. THE Schema_Context_Provider SHALL bound the schema context of every turn by the configured token budget of Requirement 4.
8. THE Model_Provider_Adapter SHALL bound the output size of every provider call by the configured maximum output tokens of Requirement 11.
9. WHILE the model provider is unavailable, THE Chat_Endpoint SHALL respond to every `POST /chat/message` request with HTTP status `503` and a body stating that the assistant is temporarily unavailable, while THE LLM_API continues to serve `GET /health` with HTTP status `200` and a body reporting a failed model-provider status.
10. WHILE the warehouse is unreachable, THE Chat_Endpoint SHALL respond to a `DATA_QUERY` turn with HTTP status `503` and a body stating that HSE data is temporarily unavailable.
11. WHILE the warehouse is unreachable, THE Chat_Endpoint SHALL continue to serve `GET /health` with HTTP status `200` and a body reporting the failed warehouse status.
12. THE LLM_API SHALL serve concurrent requests for distinct `conversation_id` values without sharing turn state, HSE scope decision, structured analytics intent, SQL statement or warehouse result set between them.
13. THE LLM_API SHALL achieve at least `80` percent line coverage as measured by `pytest --cov`.
14. THE LLM_API SHALL keep the automated test suite runtime at or below `120` seconds on the CI runner.
15. THE LLM_API SHALL decode every request body and encode every response body and every log entry as UTF-8, so that Spanish diacritics present in the user message are preserved unchanged in the synthesized answer.
16. WHEN THE LLM_API serves a `DATA_QUERY` turn on a warm execution environment, THE LLM_API SHALL bound each workflow stage at the 95th percentile of the most recent `100` such turns as follows: scope validation `1200` milliseconds, intent classification `1800` milliseconds, schema-context selection `100` milliseconds, query generation `2200` milliseconds, firewall validation `50` milliseconds, warehouse execution `1000` milliseconds, answer synthesis `1500` milliseconds, and conversation-context update `50` milliseconds, whose sum of `7900` milliseconds plus at most `100` milliseconds of request validation, response serialization and log emission equals the `8000` millisecond end-to-end target of criterion 1 and stays `17000` milliseconds below the configured turn timeout of `25000` milliseconds of Requirement 10.
17. WHEN a chat request completes, THE Request_Logger SHALL include the elapsed duration in milliseconds of every stage named in criterion 16 in the single request log entry required by Requirement 14, so that each stage budget of criterion 16 is verifiable from that entry alone.
18. THE Config_Loader SHALL expose the warehouse connection acquisition timeout as configuration with a default value of `2000` milliseconds and the per-execution-environment warehouse connection maximum as configuration with a default value of `2` connections.
19. THE Config_Loader SHALL admit a resolved configuration only if all of the following relations hold: the warehouse connection acquisition timeout plus the warehouse statement timeout is less than or equal to the turn timeout; the provider request timeout is less than the turn timeout; the warehouse statement timeout is less than the turn timeout; the turn timeout plus a response-emission margin of `2000` milliseconds is less than or equal to the API Gateway integration timeout of `29000` milliseconds; and the turn timeout governs total turn duration, so THE Agent_Orchestrator abandons a further provider attempt whenever the elapsed turn duration plus the provider request timeout exceeds the turn timeout.
20. IF the resolved configuration violates any relation of criterion 19, THEN THE LLM_API SHALL report a failed configuration status on the `GET /health` route naming the violated relation without disclosing any secret value, and THE Chat_Endpoint SHALL respond to every `POST /chat/message` request with HTTP status `503`.
21. WHEN THE LLM_API initializes a new execution environment, THE LLM_API SHALL complete initialization within `3000` milliseconds performing only configuration validation, secret resolution, approved schema allow-list loading, model-provider adapter construction and state-graph compilation, and excluding warehouse connection establishment, warehouse schema verification and dimension-value enumeration from initialization.
22. WHEN THE Query_Executor receives the first admitted SQL statement of an execution environment, THE Query_Executor SHALL establish the warehouse connection, verify that every allow-listed table and column referenced by the statement exists in the warehouse, and enumerate the dimension values it requires at that point, and SHALL reuse the established connection, the verification outcome and the enumerated values for the remaining lifetime of that execution environment.
23. WHEN THE LLM_API resolves secrets during initialization, THE LLM_API SHALL issue at most `2` requests to AWS SSM Parameter Store or AWS Secrets Manager, SHALL bound the combined resolution to `1000` milliseconds, and SHALL retain the resolved values in memory for the lifetime of the execution environment.
24. WHILE AWS SSM Parameter Store and AWS Secrets Manager are unreachable, THE Chat_Endpoint SHALL respond to every `POST /chat/message` request with HTTP status `503` and a body stating that the assistant is temporarily unavailable, while THE LLM_API continues to serve `GET /health` with HTTP status `200` and a body reporting a failed configuration status.
25. IF warehouse schema verification reports that an allow-listed table or column referenced by an admitted statement is absent from the warehouse, THEN THE Chat_Endpoint SHALL respond to that `DATA_QUERY` turn with HTTP status `503` and a body stating that HSE data is temporarily unavailable, and THE LLM_API SHALL report a failed warehouse status on the `GET /health` route.
26. WHILE the warehouse is unreachable or warehouse schema verification has failed, THE Chat_Endpoint SHALL continue to respond with HTTP status `200` to turns classified `GENERAL_CHAT` and to turns whose HSE scope decision is `OUT_OF_SCOPE` or `UNSAFE`.
27. THE LLM_API SHALL respond to at least `99.0` percent of `POST /chat/message` requests over a rolling `30`-day window with an HTTP status other than `500` and `503`, and SHALL record the error category `INTERNAL_ERROR` for at most `0.1` percent of those requests, as proposed targets pending OQ-19.
28. WHILE AWS Lambda scales THE LLM_API across additional execution environments, THE LLM_API SHALL process at most `1` chat turn per execution environment at any time and SHALL share no mutable state, including retained conversations of THE Conversation_Store, between execution environments.
29. THE Config_Loader SHALL expose the per-turn cumulative token ceiling as configuration with a default value of `12000` tokens, counting the prompt tokens and the completion tokens of every provider call of the turn.
30. IF the cumulative token count of a turn reaches the configured per-turn token ceiling, THEN THE Agent_Orchestrator SHALL terminate the turn and THE Chat_Endpoint SHALL respond with HTTP status `200` and a `response` value stating that the question could not be answered.
31. THE Agent_Orchestrator SHALL issue at most `2` warehouse queries per chat turn, each bounded by the configured statement timeout of Requirement 7 and the configured row cap of Requirement 6.
32. THE test suite SHALL execute each correctness property of Requirement 17 with at least `100` generated examples.
33. THE LLM_API SHALL confine model-provider client imports to the Model_Provider_Adapter module and warehouse driver imports to the Query_Executor module, so that the Query_Firewall module imports neither a model-provider client nor a warehouse driver and no module of the agent layer executes a SQL statement.
34. THE LLM_API SHALL limit each component module named in the Glossary section "System Names" to at most `7` public names in its module interface.
35. WHERE THE LLM_API runs on Linux under Python `3.13`, THE LLM_API SHALL produce identical response bodies, excluding the `request_id` and generated `conversation_id` values, for identical request bodies, identical configuration and identical stub dependencies, whether it runs as the AWS Lambda function or from the Docker image.
36. WHEN THE LLM_API compares a user-supplied dimension value with a value present in the corresponding warehouse dimension, THE LLM_API SHALL apply a comparison that is insensitive to letter case and to diacritic marks.

### Requirement 17: Testing

**User Story:** As a Developer, I want deterministic automated tests covering the safety-critical paths, so that CI verifies the firewall, the scope guard and the memory rules without a live model or live warehouse.

Provenance: [Notion-confirmed: Project Description §9 Definition of Done] plus the property-based-testing precedent of the sibling ETL spec; the correctness properties are [New proposed requirement].

#### Acceptance Criteria

1. THE test suite SHALL execute without calling a live model provider.
2. THE test suite SHALL execute without connecting to a live warehouse.
3. THE test suite SHALL include a deterministic stub model provider selected through the configuration value of Requirement 11 acceptance criterion 11.
4. THE test suite SHALL include a stub warehouse that returns configured result sets in place of THE Query_Executor connection.
5. THE test suite SHALL cover the question `"¿Cuántos accidentes hubo en la planta A el mes pasado?"` against a stub warehouse returning exactly one row whose aggregate value is `12`, asserting that the responded `intent` equals `DATA_QUERY`, that the answer text is Spanish, that the answer states the figure `12`, and that the answer names the resolved month and year of the period.
6. THE test suite SHALL cover a valid HSE analytics question whose stub warehouse result set contains `0` rows, asserting an answer stating that no matching records were found and asserting that the answer names the applied time range.
7. THE test suite SHALL cover one request for each out-of-scope category named in Requirement 2 acceptance criteria 4 to 7, asserting `scope_decision` equal to `OUT_OF_SCOPE`, `intent` equal to `REJECTED`, and that the stub warehouse recorded `0` statements for the turn.
8. THE test suite SHALL cover one request for each unsafe category named in Requirement 2 acceptance criteria 8 to 10 and criterion 14, asserting `scope_decision` equal to `UNSAFE`, `intent` equal to `REJECTED`, and that the stub warehouse recorded `0` statements for the turn.
9. THE test suite SHALL cover a turn in which the stub model provider returns a valid `IN_SCOPE` scope decision and a valid `DATA_QUERY` analytics intent together with a SQL-generation output containing a data-modifying statement, asserting that THE Query_Firewall rejects the statement and that the stub warehouse recorded `0` statements for the turn.
10. THE test suite SHALL cover a stub model provider that returns each of the statements `DROP TABLE fact_incidents`, `DELETE FROM fact_incidents`, `UPDATE fact_incidents SET incident_count = 0`, `INSERT INTO fact_incidents VALUES (1)`, `TRUNCATE fact_incidents`, `ALTER TABLE fact_incidents ADD COLUMN x INT`, `GRANT ALL ON fact_incidents TO llm_read`, `SELECT 1; DROP TABLE dim_date`, `SELECT * FROM fact_incidents -- LIMIT 1` and `SELECT * FROM pg_shadow LIMIT 1`, asserting that THE Query_Firewall rejects each statement.
11. THE test suite SHALL cover a SQL statement that omits a `LIMIT` clause, asserting rejection.
12. THE test suite SHALL cover a SQL statement that references `dim_text_event`, asserting rejection.
13. THE test suite SHALL cover two distinct `conversation_id` values for the `DEMO` user, asserting that the context of one conversation is absent from the context of the other.
14. THE test suite SHALL cover a request with an unknown `conversation_id`, asserting that a new conversation record is created and the supplied `conversation_id` is returned.
15. THE test suite SHALL cover submitting `11` turns to one `conversation_id` under a per-conversation turn maximum of `10`, asserting that the retained turn count equals `10` and that the oldest turn is absent from the retained turns.
16. THE test suite SHALL cover creating `101` conversations under a conversation maximum of `100`, asserting that the retained conversation count equals `100` and that the least recently used conversation is absent.
17. THE test suite SHALL cover a conversation whose most recent turn is older than the configured time-to-live, asserting that an empty context is supplied for the next turn on that `conversation_id`.
18. THE test suite SHALL cover a model-provider failure on every attempt permitted by Requirement 11 acceptance criterion 6, asserting an HTTP `503` response.
19. THE test suite SHALL cover a warehouse connection failure, asserting an HTTP `503` response.
20. THE test suite SHALL cover a warehouse statement timeout, asserting an answer stating that the question took too long to answer.
21. THE test suite SHALL cover a malformed request body, asserting an HTTP `422` response.
22. THE test suite SHALL cover a question requesting lost workdays, asserting an answer stating that the metric is unavailable.
23. THE test suite SHALL cover a question requesting employee-level analytics, asserting an answer stating that employee-level analytics are unavailable.
24. THE test suite SHALL cover a question naming an unrecognized plant, asserting an answer stating that the location was not recognized and that at most `10` location values are listed.
25. THE test suite SHALL seed every configured secret value with a distinct recognizable test value and SHALL assert that no log entry, no response body and no exception message produced during the test run contains any seeded secret value, including a turn whose user message repeats a seeded secret value verbatim.
26. THE test suite SHALL cover THE Query_Firewall, THE Conversation_Store, THE Config_Loader, THE Schema_Context_Provider and relative-date resolution by unit tests that instantiate the component directly without the HTTP layer.
27. THE test suite SHALL cover every documented behaviour of the `POST /chat/message` route and the `GET /health` route by component tests issued through the FastAPI test client with the stub model provider and the stub warehouse installed.
28. THE test suite SHALL cover the request body fields, the response body fields, the enumerated `intent` values, the enumerated `scope_decision` values and every documented HTTP status code by contract tests that read the published OpenAPI schema.
29. THE test suite SHALL execute with outbound network sockets disabled, so that any attempted network I/O raises an error and fails the test that attempted it.
30. THE stub model provider SHALL accept an independently declared canned structured output for each of the scope-decision call, the intent-classification call, the SQL-generation call and the answer-synthesis call, so that one test can declare a valid scope decision and a valid analytics intent together with an unsafe SQL-generation output.
31. IF THE Agent_Orchestrator requests a completion of a call type for which the test declared no canned output, THEN the stub model provider SHALL fail the test with an error naming the undeclared call type.
32. THE stub model provider SHALL record the invocation count per call type and SHALL expose the recorded counts to test assertions.
33. THE stub warehouse SHALL accept, per executed statement, exactly one declared outcome from the set: a result set of declared rows, a result set of `0` rows, a result set whose row count equals the configured row cap of `1000`, a statement-timeout cancellation, a connection failure, an authentication failure, an insufficient-privilege error and an undefined-column error.
34. THE stub warehouse SHALL record every received statement text in execution order and SHALL expose the recorded statements and the recorded statement count to test assertions.
35. THE test suite SHALL cover a stub model provider that returns each of the statements `WITH d AS (DELETE FROM fact_incidents RETURNING record_no) SELECT count(*) FROM d LIMIT 10`, `SELECT record_no INTO tmp_events FROM fact_incidents LIMIT 10`, `SELECT record_no FROM fact_incidents LIMIT 10 FOR UPDATE`, a statement whose text is `SELECT 1 FROM fact_incidents LIMIT 1;` followed by a newline and `DrOp TABLE dim_date`, `SELECT record_no FROM fact_incidents LIMIT ALL`, `SELECT record_no FROM fact_incidents LIMIT (SELECT 1000)`, `SELECT count(*) FROM fact_incidents, dim_date LIMIT 10`, `SELECT relname FROM pg_catalog.pg_class LIMIT 10`, `SELECT current_setting('is_superuser') LIMIT 1` and `SELECT (SELECT 1 FROM (INSERT INTO fact_incidents VALUES (1) RETURNING 1) i) LIMIT 1`, asserting that THE Query_Firewall rejects each statement.
36. THE test suite SHALL cover a stub model provider that returns each of the following statements, asserting that THE Query_Firewall admits each statement, so that over-blocking is detected: a statement whose `WHERE` clause compares `dim_cause.root_cause` to the string literal `'DROP of load from height'`, a statement whose `WHERE` clause compares `dim_status.status` to the string literal `'UPDATE PENDING'`, a statement whose `WHERE` clause compares `dim_cause.subcategory` to the string literal `'x -- y'`, a statement whose `WHERE` clause compares `dim_cause.subcategory` to the string literal `'a; b'`, a `WITH` statement whose every subquery is a `SELECT`, a statement specifying `LIMIT 1000`, and an aggregate statement carrying `GROUP BY`, `HAVING` and `ORDER BY` clauses.
37. THE test suite SHALL cover a question about personal protective equipment against a stub warehouse in which one `record_no` carries `3` rows in `bridge_incident_ppe`, asserting that the answer states an event count of `1` and that the admitted statement counts distinct `record_no` values.
38. THE test suite SHALL cover a question combining an incident count and a corrective-action count against a stub warehouse in which one `record_no` carries `4` rows in `fact_actions`, asserting that the stated incident count equals `1` and is not multiplied by the corrective-action row count.
39. THE test suite SHALL cover a question about corrective-action totals against a stub warehouse containing a zero-action sentinel row, asserting that the stated action total for the sentinel event equals `0` and that the event is counted exactly once.
40. THE test suite SHALL cover a grouped analytics question, asserting that every non-aggregated column of the admitted statement's select list is present in the statement's `GROUP BY` clause.
41. WHEN the stub model provider returns a draft answer whose stated numeric value differs from the numeric value in the stub warehouse result set, THE test suite SHALL assert that THE Answer_Synthesizer requests exactly one regeneration, and that if the regenerated draft still states a value differing from the result-set value the returned answer is produced from the deterministic template and states the result-set value.
42. THE test suite SHALL cover two turns submitted concurrently for one `conversation_id`, asserting that both turns receive an HTTP `200` response, that the retained turn count for that conversation equals `2`, and that neither turn's context contains the other turn's answer.
43. THE test suite SHALL cover filling THE Conversation_Store to its configured maxima of `100` conversations, `10` turns per conversation and `2000`-character messages, asserting that the retained conversation count equals `100`, that no conversation retains more than `10` turns, and that the total retained character count is at or below the configured conversation-store character budget.
44. THE test suite SHALL assert that each request log entry contains exactly the field set required by Requirement 14 and that the serialized entry parses as one JSON object containing `0` embedded newline characters.
45. WHILE the configured log level is `INFO`, THE test suite SHALL assert that no log entry contains the raw user message text and that no log entry contains the executed SQL statement.
46. THE test suite SHALL assert that exactly `1` log entry is emitted per request for each terminal path, namely request-validation failure, scope rejection, clarification request, general chat, successful data query, firewall rejection after the permitted regeneration, analytics-intent validation failure, provider-retry exhaustion, warehouse connection failure, warehouse statement timeout and turn timeout.
47. WHEN startup validation runs against a configuration in which `3` required keys are absent, THE test suite SHALL assert that the reported validation failure names all `3` absent keys in a single report and discloses no secret value.
48. IF a resolved configuration names the production environment together with a log level of `DEBUG` or together with the stub model provider, THEN THE test suite SHALL assert that THE Config_Loader fails startup validation and names the offending configuration key.
49. IF a resolved configuration specifies a statement timeout that is not strictly less than the turn timeout, or a provider request timeout that is not strictly less than the turn timeout, THEN THE test suite SHALL assert that THE Config_Loader fails startup validation and names the offending configuration keys.
50. THE test suite SHALL resolve every relative-date test against an injected frozen reference timestamp, SHALL advance conversation time-to-live and timeout tests through an injected clock, and SHALL contain `0` wall-clock sleep calls.
51. THE test suite SHALL achieve at least `80` percent line coverage when executed as `uv run --locked pytest --cov=. --cov-report=xml --cov-report=term-missing`, and SHALL emit the XML coverage report that the SonarQube scan consumes.
52. THE test suite SHALL achieve at least `95` percent line coverage and at least `90` percent branch coverage for each of THE Scope_Guard, THE Query_Firewall, THE Query_Executor, THE Conversation_Store, THE Config_Loader and THE Request_Logger.
53. THE test suite SHALL declare every stub warehouse result set with at most `20` rows, SHALL exclude any test fixture file larger than `50` kilobytes, and SHALL replace every external I/O boundary, namely the model provider, the warehouse, the secret store and the system clock, with a test double.

#### Correctness Properties

The following properties SHALL be verified with property-based tests using Hypothesis. Each property is stated so that a generated counterexample identifies a defect. Each property SHALL map to exactly one property-based test, each such test SHALL carry a tagging comment of the form `# Feature: hse-llm-chatbot-api, Property {number}: {property_text}`, and each such test SHALL declare `@settings(max_examples=100, deadline=None)` so that at least `100` examples run per property.

1. **Firewall soundness (allow-list invariant):** FOR ALL generated SQL strings, THE Query_Firewall SHALL admit the string only if the string is a single statement whose first keyword is `SELECT` or `WITH`, whose referenced table and column identifiers are all present in the approved schema allow-list, and which specifies a `LIMIT` value less than or equal to the configured row cap.
2. **Firewall rejection completeness:** FOR ALL generated SQL strings containing a DDL keyword token, a DML keyword token, a comment token, or a statement separator followed by non-whitespace content, THE Query_Firewall SHALL reject the string.
3. **Firewall determinism / idempotence:** FOR ALL generated SQL strings, repeated evaluation by THE Query_Firewall SHALL produce the same verdict and the same rejection reason code.
4. **Firewall independence from instructions:** FOR ALL generated user messages paired with a fixed unsafe SQL string, THE Query_Firewall SHALL reject the SQL string.
5. **Conversation isolation:** FOR ALL pairs of distinct `conversation_id` values and all sequences of turns applied to them, the context supplied for one `conversation_id` SHALL contain only turns recorded under that `conversation_id`.
6. **Memory bound invariant:** FOR ALL sequences of turns applied to THE Conversation_Store, the retained turn count per conversation SHALL be less than or equal to the configured per-conversation turn maximum, the retained conversation count SHALL be less than or equal to the configured conversation maximum, and the total retained character count SHALL be less than or equal to the configured conversation-store character budget.
7. **Scope-guard ordering invariant:** FOR ALL generated user messages, a warehouse execution SHALL occur only when the recorded HSE scope decision for that turn is `IN_SCOPE`.
8. **Relative-date round trip:** FOR ALL generated reference timestamps and all supported relative month expressions, resolving the expression and then formatting the resolved start and end dates and resolving them again SHALL produce the same start and end dates.
9. **Answer fidelity:** FOR ALL generated warehouse result sets containing a single numeric aggregate, the numeric value stated in the synthesized answer SHALL equal the numeric value in the result set.
10. **Response contract invariant:** FOR ALL generated request bodies, a successful response SHALL contain the fields `response`, `conversation_id`, `user_id`, `intent`, `request_id` and `scope_decision`, and `user_id` SHALL equal `DEMO`.
11. **Firewall false-positive freedom on string literals:** FOR ALL generated single-quoted string literals containing any keyword token of Requirement 6 acceptance criterion 7, a comment token or a statement separator, THE Query_Firewall SHALL admit the statement that selects `dim_cause.root_cause` from `dim_cause` where `dim_cause.root_cause` equals that literal and specifies a `LIMIT` value within the configured row cap.
12. **Allow-list closure:** FOR ALL generated SQL strings that THE Query_Firewall admits, every table identifier and every column identifier referenced by the admitted string SHALL be present in the approved schema allow-list.
13. **Bridge fan-out invariance:** FOR ALL generated incident row sets and bridge row sets, the event count reported for a statement that joins `bridge_incident_ppe` or `bridge_incident_injury` SHALL equal the event count reported for the same statement evaluated without the bridge join.
14. **Turn-outcome totality:** FOR ALL generated request bodies paired with all declared stub outcomes, each turn SHALL terminate with exactly one value of the enumerated turn-outcome set of Requirement 10 acceptance criterion 33.
15. **Log-entry totality and redaction:** FOR ALL generated request bodies paired with all declared stub outcomes, the turn SHALL produce exactly one request log entry, and that entry SHALL contain no seeded secret value.
16. **Timeout-ordering invariance:** FOR ALL generated configuration value sets that THE Config_Loader admits, the configured statement timeout SHALL be strictly less than the configured turn timeout and the configured provider request timeout SHALL be strictly less than the configured turn timeout.
17. **Model-call bound invariance:** FOR ALL generated request bodies paired with all declared stub outcomes, the number of model-provider calls recorded for the turn SHALL be less than or equal to the configured per-turn model-call maximum.

## Backlog Traceability

Mapping of the confirmed Epic 04 "Chatbot Cognitivo" backlog onto this specification [Notion-confirmed: Epic 04 backlog].

| Notion user story | Points / Sprint | Covered by |
|---|---|---|
| US-4.1 Orquestador de Intención (Semantic Analysis) | 5 / Sprint 9 | Requirement 3 (classification `DATA_QUERY` / `GENERAL_CHAT`, clarification), Requirement 2 AC 4–12 (rejection of non-industrial-safety requests) |
| US-4.2 Generación de SQL con IA (Text-to-SQL) | 13 / Sprint 9 | Requirement 4 (schema in prompt, token bounding, few-shot pairs), Requirement 5 (valid PostgreSQL, single `SELECT`) |
| US-4.3 Firewall de Consultas (Security Layer) | 5 / Sprint 10 | Requirement 6 (starts with `SELECT`, rejects `;`, `DROP`, `DELETE`, `UPDATE`, `TRUNCATE`), Requirement 7 (read-only role) |
| US-4.4 Síntesis de Respuesta (Natural Language Response) | 3 / Sprint 10 | Requirement 9 (natural sentence with the figure, zero-result handling) |

### Additions Beyond the Confirmed Backlog

These requirements have no corresponding Notion backlog item and require Product Owner acceptance:

| Requirement | Addition |
|---|---|
| Requirement 2 (partly) | Pre-warehouse ordering guarantee; credential-exfiltration and data-modification rejection categories |
| Requirement 4 | Approved schema allow-list as an independently enforced configuration artifact; exclusion of `dim_text_event` |
| Requirement 6 (partly) | Allow-list enforcement, statement-count enforcement, comment rejection, mandatory `LIMIT`, row cap, extended keyword set, non-LLM verdict guarantee |
| Requirement 7 (partly) | Named `llm_read` role, `default_transaction_read_only`, statement timeout, credential secret paths |
| Requirement 10 | LangGraph controlled workflow with fixed node sequence and per-turn model-call cap |
| Requirement 11 | Model-provider abstraction with configurable provider and model |
| Requirement 12 | Conversation memory, isolation, TTL and eviction |
| Requirement 14 | Per-request logging with a bounded error-category set and log redaction rules |
| Requirement 15 (partly) | Docker-based local execution |
| Requirement 17 | Deterministic stub provider and stub warehouse; Hypothesis correctness properties |

## Assumptions and Recorded Decisions

| ID | Statement | Basis |
|---|---|---|
| A-1 | The MVP has no authentication, user management, authorization or RBAC; every conversation belongs to `DEMO`. This supersedes Project Description §10.2 for this service only and is recorded as an accepted deviation. | [User-directed] — see OQ-7, R-3 |
| A-2 | LangGraph is the orchestration framework, superseding the LangChain note in Project Description §2.2 and US-4.1. Rationale: an explicit controlled state machine gives a fixed, auditable node sequence, which the safety requirements depend on. | [User-directed] — see OQ-10 |
| A-3 | Python 3.13 is the target runtime, superseding the Python 3.11 statement in Project Description §2.2. The repository `.python-version` and `pyproject.toml` already declare 3.13. | [Repo-confirmed], [User-directed] — see OQ-11 |
| A-4 | Physical warehouse identifiers are lowercase English (`fact_incidents`, `dim_date`, `dim_location`). The PascalCase names in Project Description §10.1 and the example SQL in §4.4 (`FROM Fact_Incidentes`) are stale. | [Notion-confirmed: Data Warehouse Schema] — see OQ-3 |
| A-5 | The reference timezone for relative date expressions is `America/Bogota`, and relative month boundaries are inclusive of the first and last calendar day. | [Assumption] — see OQ-16 |
| A-6 | The assistant answers in the language of the user message by default, with a configuration option to fix the language. | [Assumption] — see OQ-13 |
| A-7 | `query_executed` is omitted from the response by default and exposed only when explicitly enabled, because returning raw SQL discloses schema structure. | [Assumption] — see OQ-8 |
| A-8 | Week-level trends are derived from `dim_date.date`; no week column is added to the warehouse for this MVP. | [Notion-confirmed: Data Warehouse Schema] — see OQ-4 |
| A-9 | Lost-workday and employee-level analytics are unsupported in the MVP and the assistant reports the metrics as unavailable rather than substituting a proxy. | [Notion-confirmed: Data Warehouse Schema] — see OQ-1, OQ-2 |
| A-10 | Answers describe figures as covering finalized Colombia and "The Americas" incidents, reflecting `transform.filter_to_scope`. | [Notion-confirmed: Data Warehouse Schema] — see OQ-6 |
| A-11 | The MVP contract is `POST /chat/message` with `{ message, conversation_id }` and a server-fixed `user_id = "DEMO"`; `conversation_id` replaces the documented `session_id`, and a supplied `user_id` is ignored. | [User-directed] reconciled with [Notion-confirmed: Project Description §4.4] — see OQ-8 |
| A-12 | Conversation storage is in application memory for this release, behind an interface that a persistent implementation can satisfy. | [User-directed] — see OQ-14, R-5 |
| A-13 | The default configuration values stated in the requirements (row cap `1000`, statement timeout `10000` ms, turn timeout `25000` ms, provider timeout `15000` ms, schema token budget `4000`, per-conversation turns `10`, conversations `100`, TTL `1800` s, model calls per turn `4`) are starting values subject to tuning against measured behaviour. | [Assumption] — see OQ-19 |
| A-14 | The proposed SSM parameter paths for the read-only role are `/kognit/db/LLM_READ_USER` and `/kognit/db/LLM_READ_PASSWORD`, following the existing `/kognit/db/*` convention. | [New proposed requirement] — see OQ-9 |
| A-15 | The `GET /health` route remains unauthenticated and continues to report warehouse connectivity, matching the current implementation. | [Repo-confirmed], [Notion-confirmed: Project Description §10.2] |
| A-16 | The Statistics API, the ML API, the ETL and the warehouse schema are unchanged by this work. | [Assumption] |

## Risks

| ID | Risk | Impact | Mitigation |
|---|---|---|---|
| R-1 | Text-to-SQL produces syntactically valid but semantically wrong SQL, yielding a confident but incorrect figure. | High — erodes trust in HSE reporting | Bound the allow-list, use few-shot pairs (Requirement 4 AC 12), state applied filters in every answer (Requirement 9 AC 2), verify answer fidelity by property test (Requirement 17 property 9). Documented as HIGH RISK in US-4.2 [Notion-confirmed] |
| R-2 | Prompt injection persuades the model to emit DDL or DML. | High — potential data loss | Non-LLM firewall (Requirement 6), read-only `llm_read` role (Requirement 7), property tests 1, 2, 4 (Requirement 17) |
| R-3 | The endpoint carries no authentication in the MVP, conflicting with Project Description §10.2 and with the frontend Axios auth interceptor. | High if exposed publicly | Accepted, documented deviation (A-1); Requirement 13 AC 12–13 keep the contract auth-ready and require the exposure risk to be documented; OQ-7 escalates the deployment decision |
| R-4 | Schema context grows past the model token limit as the allow-list widens. | Medium — degraded accuracy or provider errors | Token budget (Requirement 4 AC 9–10), intent-driven context selection (Requirement 4 AC 8). Documented as HIGH RISK in US-4.2 [Notion-confirmed] |
| R-5 | In-memory conversation state is lost on AWS Lambda cold starts and is not shared across concurrent execution environments, so conversation continuity is best-effort in the deployed environment. | Medium — inconsistent follow-up answers | Documented limitation (Requirement 12 AC 20–21), storage interface for a persistent backend (Requirement 12 AC 19), OQ-14 |
| R-6 | The LangGraph plus model-provider dependency set may exceed the AWS Lambda deployment package limits of `250` MB uncompressed and `50` MB compressed. `build.sh` already exports a `requirements.txt` from `uv.lock` via `uv export --frozen --no-dev --no-editable` and installs for `x86_64-manylinux2014` on Python `3.13`, so the dependency-source gap previously recorded here does not exist. | Medium — deployment failure | Requirement 15 AC 12–13, AC 32–35; measure artifact size in CI and fall back to a container image or Lambda layer. See D-6, OQ-17 |
| R-13 | `build.sh` adds application code with `zip -r "$ZIP_PATH" src/*.py`, a glob that matches only top-level `.py` files in `src`. A modular implementation that places code in subpackages such as `src/agent/` or `src/db/` would be silently omitted from the artifact, producing an import failure only at runtime in Lambda. | High — a passing CI build can still deploy a broken artifact | Requirement 15 AC 39–40 require every module and subpackage of `src` to be present in the artifact and require the build to verify that `handler` and its transitive imports are included |
| R-7 | The warehouse sits in a private subnet, so the Lambda must be VPC-attached, which removes default outbound internet access to the model provider. | High — the service cannot reach the model provider | Dependency D-4 (NAT gateway or VPC endpoint), OQ-15 |
| R-8 | `dim_location.plant` values are masked, so user phrasing such as "Planta A" may not match any stored value. | Medium — unanswerable questions | Requirement 8 AC 10–11 resolve against stored values and report unrecognized locations, OQ-5 |
| R-9 | Model-provider cost and rate limits grow with traffic and with retries. | Medium — cost overrun | Per-turn model-call cap (Requirement 10 AC 5–6), token accounting in logs (Requirement 11 AC 10), bounded retries (Requirement 11 AC 6) |
| R-10 | AWS credentials in GitHub Actions are Vocareum lab credentials that expire each session, so deployments can fail unpredictably. | Medium — blocked releases | [Notion-confirmed: CI/CD Pipelines]; dependency D-5 |
| R-11 | `bridge_incident_injury` exists in ETL code but is absent from the design DDL block, and `dim_equipment.equipment_category` is documented as drift. | Low to medium — queries against drifted objects may fail | Verify object existence before adding to the allow-list; OQ-20 |
| R-12 | Returning `query_executed` discloses schema structure to any client that reaches the unauthenticated endpoint. | Medium — information disclosure | Disabled by default (Requirement 1 AC 12–14, A-7) |

## Dependencies

| ID | Dependency | Status |
|---|---|---|
| D-1 | HSE data warehouse loaded by the ETL, with the tables and columns named in Requirement 8. | [Notion-confirmed: Data Warehouse Schema] — available |
| D-2 | Provisioning of the read-only PostgreSQL role `llm_read` with `CONNECT`, `USAGE` and `SELECT` only, and its credentials stored in SSM or Secrets Manager. | [New proposed requirement] — blocking, see OQ-9 |
| D-3 | A model provider account, chosen model, region and credential path. | [Open question] — blocking, see OQ-12 |
| D-4 | Network path from the Lambda to the warehouse private subnet, and outbound network path from the Lambda to the model provider. | [Open question] — blocking, see OQ-15, R-7 |
| D-5 | Working AWS deployment credentials in GitHub Actions. | [Notion-confirmed: CI/CD Pipelines] — time-limited, see R-10 |
| D-6 | Lambda packaging that carries the LangGraph and provider dependencies and the full `src` package tree within the Lambda size limits. `build.sh` already derives dependencies from `uv.lock`; the open items are artifact size and the `src/*.py` glob. | [Repo-confirmed] — see R-6, R-13, OQ-17 |
| D-7 | Frontend `ChatInterface` component on route `/chat`, including loading and empty-state views. | [Notion-confirmed: Project Description] — parallel work |
| D-8 | US-5.4 and US-1.5, named as prerequisites of US-4.1 and US-4.2 respectively. | [Notion-confirmed: Epic 04 backlog] — verify status before Sprint 9 |
| D-9 | The confirmed value set of `LOCATION_MASK` used by `transform.mask_locations`. | [Open question] — see OQ-5 |

## Open Questions

| ID | Question | Status | MVP behaviour until resolved | Answer
|---|---|---|---|---|
| OQ-1 | Is lost-workday analysis in MVP scope, and if so does the warehouse need a new measure or a preserved raw severity code? Project Description §3.2 lists `dias_perdidos`, but the authoritative schema has only `incident_count` and `severity_index`, and `S3b` (Lost time, LTA) collapses into `serious`. | Resolved — Product Owner | Requirement 8 AC 6: report the metric as unavailable | Answer: The MVP does not cover lost workday analysis so this can be safely ignored.|
| OQ-2 | Should an employee dimension be added? Project Description §3.2 lists `Dim_Empleado` with SCD Type 2, and the authoritative schema has no employee dimension. Adding one introduces employee PII handling obligations. | Resolved — Product Owner and Data Owner | Requirement 8 AC 7: report employee-level analytics as unavailable | Answer: No Employee dimension is not covered in this MVP, so this analysis is also out of scope.|
| OQ-3 | Should Project Description §10.1 and the §4.4 example SQL be corrected to the lowercase English physical names? | Resolved — documentation owner | A-4: treat the authoritative schema as correct | Answer: The project description was a first attempt to define the project but we should stick to the schema as correct and updated version.|
| OQ-4 | Should `dim_date` gain a week attribute, or is derivation from `dim_date.date` acceptable long-term? | Resolved — Data Engineering | A-8: derive with `EXTRACT(WEEK ...)` / `date_trunc('week', ...)` | Answer: It should be a derivation, no changes to the star model will be made in the near future.|
| OQ-5 | What is the `LOCATION_MASK` value set, and how should user phrasing such as "Planta A" or "planta norte" map to a stored `dim_location.plant` value? | Resolved — Data Engineering | Requirement 8 AC 10–11: resolve against stored values, report unrecognized locations | Answer: The ETL that populates the data warehouse follows a conversion table but for the agent and this MVP just be sure to check the unique values of the dim.location.plant. No need to know what the real names of the plants are.|
| OQ-6 | Should the answer text always state the Colombia / "The Americas" scope, or only when the question implies broader coverage? | Resolved — Product Owner | Requirement 8 AC 12–13: state the scope | Answer: We should always mention that the coverage is only in Colombia for this MVP.|
| OQ-7 | Project Description §10.2 mandates Bearer Token authentication on all endpoints except `/health`, and the frontend already sends an auth token. The MVP excludes authentication. Is the service deployed behind an authenticating layer, or is unauthenticated exposure accepted? | resolved — Security and Product Owner | A-1, Requirement 13 AC 12–13: auth-ready contract and documented risk | Answer: no authentication is done so this can be ignored. This will be modified as well in the corresponding user story.|
| OQ-8 | Confirm the reconciled contract: `conversation_id` in place of `session_id`, server-fixed `user_id = "DEMO"`, and `query_executed` omitted by default. | Resolved — Frontend and Product Owner | A-7, A-11 | answer: yes let's use conversation_id and the proposed approach for user_id and query_executed.|
| OQ-9 | Confirm provisioning of `llm_read`, its grant set, whether `default_transaction_read_only` is set on the role, and the SSM paths for its credentials (proposed `/kognit/db/LLM_READ_USER`, `/kognit/db/LLM_READ_PASSWORD`). | Resolved — Database owner | A-14, Requirement 7 | Answer: yes let's do it like that, the credentials will be taken from SSM. DBA has created the user and will store those credentials in the SSM.|
| OQ-10 | Confirm that LangGraph supersedes the LangChain note in Project Description §2.2 and US-4.1. | Decision recorded, confirmation pending | A-2 | Answer: Yes we will use LangGraph.|
| OQ-11 | Confirm that Python 3.13 supersedes the Python 3.11 statement in Project Description §2.2. | Decision recorded, confirmation pending | A-3 | Answer: Yes we're using Python 3.13|
| OQ-12 | Which model provider and model serve the MVP, in which region, under which quota, and where do the credentials live? | Resolved | Requirement 11: provider abstraction, no hard-coded model | Answer: The credentials will live in the SSM.|
| OQ-13 | Should the assistant answer in the language of the question, or in a fixed language? | Resolved — Product Owner | A-6: language of the question by default | Answer: The assistant can answer in spanish and english. No other languages allowed.|
| OQ-14 | Is best-effort conversation continuity acceptable for the MVP, or is a persistent store required before release? | Resolved — Product Owner | A-12, Requirement 12 AC 18–21 | Answer: conversation history will only live during the session Answer: best-effort continuity is acceptable for the MVP, with explicit limitations. A persistent store is not required before the MVP release as the release is a controlled demo, internal pilot, or single-instance deployment—not a production-grade multi-instance service.|
| OQ-15 | Which network configuration gives the Lambda access to both the private-subnet warehouse and the external model provider (NAT gateway, VPC endpoint, or provider inside the VPC)? | Resolved | D-4, R-7 | Answer: this is granted through a NAT gateway which is already configured and working.|
| OQ-16 | Confirm the reference timezone `America/Bogota` and inclusive month boundaries for relative date expressions. | Resolved — Product Owner | A-5, Requirement 3 AC 8–11 | Answer: Yes the timezone must be 'America/Bogota'|
| OQ-17 | Does the LangGraph plus model-provider dependency set fit inside the Lambda limits of `250` MB uncompressed and `50` MB compressed, and if not, is a container image or a Lambda layer approved as the packaging path? | Resolved — Development team and Infrastructure | Requirement 15 AC 13, AC 34–35; measure and fail the build on breach | Answer: Yes it should fit that limit, make sure that the bundler (build.sh) only keeps the required libraries, so no dev dependencies should be included.|
| OQ-21 | The Notion "CI/CD Pipelines" page shows a `build.sh` that installs from a checked-in `requirements.txt` and a health-check payload targeting `/api/v1/health`. The committed repository instead exports `requirements.txt` from `uv.lock` at build time and the committed payload targets `/health`. Should the Notion page be corrected to match the repository? | Resolved — documentation owner | Treat the committed repository as authoritative; Requirement 15 AC 15, AC 32–33, AC 37 | Answer: yes the notion page is outdated and will be updated.|
| OQ-18 | Is a Dockerfile and Compose definition accepted as the local development path for this service, given that no container setup exists in the repository today? | Resolved — Development team | Requirement 15 AC 8–11 | Answer: Not needed actually.|
| OQ-19 | What is the accepted latency target for a chat turn? Notion documents targets for ML inference (<500 ms), BI dashboards (<3 s) and ETL (<10 min), and none for chat. | Resolved — Product Owner | Requirement 16 AC 1–3 as proposed targets | Answer: Around 1-2 seconds, but be sure that the chat response is in stream mode to improve user experience.|
| OQ-20 | Do `bridge_incident_injury` and `dim_equipment.equipment_category` exist in the deployed warehouse, given the documented drift between ETL code and the design DDL? | Resolved — Data Engineering | Verify before adding to the allow-list; R-11 | Answer: They both exist.|

## Future Work (Explicitly Not MVP Requirements)

1. Structured centralized logging with a log aggregation platform.
2. Distributed tracing across the frontend, the LLM API, the Statistics API and the warehouse.
3. Monitoring dashboards and alerting on rejection rates, firewall rejections, latency and provider errors.
4. Query auditing with retained SQL history and per-query attribution.
5. Model observability, including prompt versioning, answer-quality evaluation and drift detection.
6. Persistent conversation storage behind the Requirement 12 storage interface.
7. Bearer Token authentication, user identity and per-user authorization.
8. Semantic and embedding search over `dim_text_event` narrative content, with a PII review.
9. Lost-workday and employee-dimension analytics, contingent on OQ-1 and OQ-2.
10. Response streaming and chart or table rendering in the frontend.

## Implementation Milestones

Each milestone is independently testable and traces to requirement identifiers. Notation `R7.2` means Requirement 7, acceptance criterion 2.

| # | Milestone | Traces to | Done when |
|---|---|---|---|
| M-1 | Configuration and health baseline: Pydantic-validated environment configuration, secret resolution, extended `GET /health` reporting warehouse and provider-configuration status. | R1.18–R1.19, R7.8–R7.10, R13.1–R13.4, R15.6–R15.7, R15.16–R15.27 | `GET /health` reports both statuses; a missing required key is named without disclosing secrets |
| M-2 | Chat contract skeleton: `POST /chat/message` with Pydantic request and response models, fixed `DEMO` user, `conversation_id` generation, validation errors, OpenAPI schema. Returns a static answer. | R1.1–R1.11, R1.15–R1.17, R1.20–R1.22 | Contract tests pass for valid, missing, empty and oversized `message` |
| M-3 | Approved schema allow-list artifact: single configuration artifact listing allowed tables, columns and measures, excluding `dim_text_event`, with intent-driven selection and token budget. | R4.1–R4.34 | Allow-list unit tests assert inclusion of the fact, dimension and bridge tables and exclusion of `dim_text_event` |
| M-4 | Query firewall: deterministic non-LLM validator with keyword, statement-count, comment, allow-list, `LIMIT` and row-cap rules. | R6.1–R6.46, R13.5–R13.6 | Unit tests for every rejection case in R17.10–R17.12 pass; Hypothesis properties 1–4 hold |
| M-5 | Read-only executor: `llm_read` connection, read-only transaction, statement timeout, row-cap truncation, execution-duration capture. | R7.1–R7.35, R16.5–R16.6 | Stub-warehouse tests assert read-only session settings, timeout handling and truncation |
| M-6 | Model provider abstraction: provider-independent structured-output interface, configurable provider and model, retries, timeout, token accounting, deterministic stub. | R11.1–R11.33, R16.8 | Tests run with the stub provider; retry and timeout paths return `503` |
| M-7 | Scope guard: HSE scope decision for every rejection category, guaranteed before warehouse access, with a user-facing rejection message. | R2.1–R2.18, R13.7–R13.9, R13.23–R13.28 | Tests assert no warehouse call for every out-of-scope and unsafe category; Hypothesis property 7 holds |
| M-8 | Intent classification and relative-date resolution: `DATA_QUERY` / `GENERAL_CHAT` / `CLARIFICATION_NEEDED`, structured analytics intent, timezone-aware date resolution. | R3.1–R3.45 | Classification tests pass; Hypothesis property 8 holds |
| M-9 | SQL generation: single-statement, allow-listed, `LIMIT`-bearing PostgreSQL SQL with few-shot prompting and one bounded regeneration attempt. | R5.1–R5.35, R4.12 | Stub-provider tests produce firewall-admitted SQL; the regeneration path is exercised |
| M-10 | Answer synthesis: figure-bearing natural-language answers, zero-result answers, truncation notice, language handling, redaction. | R9.1–R9.33 | Non-empty and empty result cases pass; Hypothesis property 9 holds |
| M-11 | Analytics coverage and unsupported-metric handling: coverage of the supported categories; unavailable responses for lost workdays, employee analytics, frequency rate and narrative text; unrecognized-location handling; data-scope statement. | R8.1–R8.37 | One test per coverage-matrix row, including every unsupported case |
| M-12 | Conversation memory: in-memory store keyed by `conversation_id`, isolation, per-conversation turn cap, conversation cap with LRU eviction, TTL, storage interface. | R12.1–R12.38 | Isolation, unknown-id, eviction and TTL tests pass; Hypothesis properties 5–6 hold |
| M-13 | Controlled LangGraph workflow: fixed node sequence wiring M-3 through M-12, per-turn model-call cap, turn timeout, terminal-node recording. | R10.1–R10.33, R16.1–R16.4, R16.9–R16.12, R16.16–R16.31 | End-to-end stub tests traverse the fixed sequence; degraded provider and warehouse paths return `503` |
| M-14 | Logging: one redacted single-line JSON entry per request with the required fields and bounded error categories. | R14.1–R14.38, R17.25, R17.44–R17.46 | Log-content tests assert required fields present and secrets absent |
| M-15 | Quality gates and packaging: Ruff clean, Ty clean, coverage at or above 80 percent, Dockerfile and Compose for local runs, Lambda packaging including the new dependencies, CD health-check payload passing. | R15.1–R15.5, R15.8–R15.15, R15.28–R15.40, R16.13–R16.15, R16.32–R16.36, R17.1–R17.4 | CI `quality-and-tests` passes; the Docker image serves both routes; the published Lambda version returns `statusCode` `200` |
