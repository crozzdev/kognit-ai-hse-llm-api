from kognit_llm.safety.scope_rules import match_category

for msg in [
    "que tipos de preguntas puedes responder?",
    "hola, que puedes hacer?",
    "cuantos incidentes hubo el mes pasado",
]:
    print(repr(msg), "->", match_category(msg))
