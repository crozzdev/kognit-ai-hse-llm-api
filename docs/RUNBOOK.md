# Runbook — Servicio LLM en local (Bedrock Sonnet 4.6 + Postgres Docker)

Guía paso a paso para levantar, probar y detener el microservicio LLM en tu máquina.
Todo corre en **WSL (Ubuntu)**, no en PowerShell (el `.venv` es de Linux).

---

## 0. Requisitos previos (verificar una vez)

Antes de arrancar, confirma que estas tres cosas están listas:

1. **Docker Desktop corriendo** con el contenedor `postgres-db` (Postgres 17 con el star schema).
2. **Perfil AWS `bedrock`** configurado en `C:\Users\57318\.aws`.
3. Estás en la rama correcta del submódulo LLM: `feat/us4-llm_agent`.

### Comprobaciones rápidas (en PowerShell)

```powershell
# ¿El contenedor de Postgres está arriba?
docker ps --format "table {{.Names}}\t{{.Ports}}\t{{.Status}}"
# Debe listar: postgres-db ... 0.0.0.0:5434->5432/tcp ... Up
```

Si `postgres-db` no aparece, arráncalo:

```powershell
docker start postgres-db
```

---

## 1. Abrir WSL en la carpeta del servicio

Todo lo demás se hace **dentro de WSL**. Abre una terminal WSL/Ubuntu y entra a la carpeta:

```bash
cd /mnt/c/Proyectos/kognit-ai-hse-frontend/services/kognit-ai-hse-llm-api
```

---

## 2. (Solo si es la primera vez del día) sincronizar dependencias

```bash
uv sync
```

Esto asegura que el `.venv` tenga todo lo del `uv.lock`. Si ya lo corriste antes y no cambió nada, es rápido.

---

## 3. Arrancar el servicio

Copia y pega este bloque completo en WSL. Exporta toda la configuración
(Bedrock + Postgres) y arranca uvicorn:

```bash
# --- AWS / Bedrock (Claude Sonnet 4.6 via inference profile) ---
export AWS_PROFILE=bedrock
export AWS_SHARED_CREDENTIALS_FILE=/mnt/c/Users/57318/.aws/credentials
export AWS_CONFIG_FILE=/mnt/c/Users/57318/.aws/config
export KOGNIT_LLM_MODEL_PROVIDER=bedrock
export KOGNIT_LLM_MODEL_ID="arn:aws:bedrock:us-east-1:319797801226:inference-profile/global.anthropic.claude-sonnet-4-6"
export KOGNIT_LLM_AWS_REGION=us-east-1

# --- Warehouse (tu Postgres en Docker) ---
export KOGNIT_LLM_ENVIRONMENT=local
export KOGNIT_LLM_DB_HOST=127.0.0.1
export KOGNIT_LLM_DB_PORT=5434
export KOGNIT_LLM_DB_NAME=postgres
export KOGNIT_LLM_DB_SCHEMA=public
export KOGNIT_LLM_DB_USER=admin
export KOGNIT_LLM_DB_PASSWORD=admin123
export KOGNIT_LLM_DB_SSLMODE=disable

# --- Arrancar (PYTHONPATH=src es imprescindible) ---
export PYTHONPATH=src
uv run uvicorn src.main:app --host 127.0.0.1 --port 8000
```

**Listo cuando veas:**

```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

Deja esta terminal abierta: el servicio corre aquí. Para detenerlo, `Ctrl+C`.

---

## 4. Probar el servicio

Abre **otra** terminal (WSL o el navegador). Tres opciones:

### Opción A — Navegador (la más cómoda)

Abre `http://127.0.0.1:8000/docs` → busca **POST /chat/message** →
**Try it out** → escribe el body → **Execute**.

### Opción B — curl (otra terminal WSL)

```bash
curl -s -X POST http://127.0.0.1:8000/chat/message \
  -H 'Content-Type: application/json' \
  --data '{"message": "how many incidents were recorded in 2025?"}'
```

Respuesta esperada (aprox): `"169 incidents were recorded during 2025."`

### Preguntas de ejemplo que funcionan

- `how many incidents were recorded in 2025?`
- `how many incidents were there last year?`
- `incidents by location in 2025`

> **Rango de datos:** las fechas van de **2023-05 a 2026-01**. Pregunta por periodos
> dentro de ese rango (2025, "last year"). "febrero 2026" no tiene datos.

> **Idioma:** el modelo responde mejor en inglés. En español también clasifica,
> pero el número puede tardar (cada consulta llama a Bedrock, ~15-30s).

---

## 5. Detener el servicio

En la terminal donde corre uvicorn: **`Ctrl+C`**.

Para confirmar que el puerto quedó libre (opcional):

```bash
ss -ltn | grep 8000 || echo "puerto 8000 libre"
```

---

## Verificación rápida (sin Bedrock ni Postgres)

Si solo quieres comprobar que el código está sano, sin nada externo:

```bash
cd /mnt/c/Proyectos/kognit-ai-hse-frontend/services/kognit-ai-hse-llm-api
uvx ruff@0.15.0 check .
uvx ty@0.0.29 check
uv run --locked pytest -q
```

Esperado: ruff/ty "All checks passed", pytest "48 passed".

---

## Solución de problemas

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `scope_decision: OUT_OF_SCOPE` en todo | El modelo no tiene acceso (AccessDenied) | Revisa que el ARN de Sonnet 4.6 siga con acceso en Bedrock → Model access. O usa Nova: `export KOGNIT_LLM_MODEL_ID=amazon.nova-pro-v1:0` |
| Respuesta "could not be completed" + 503 | Postgres no accesible | `docker start postgres-db`; confirma puerto 5434 |
| `PoolClosed` / warehouse error | (Ya arreglado en código) | Asegúrate de estar en el último commit de `feat/us4-llm_agent` |
| El curl cuelga muchos segundos | Normal: cada turno llama a Bedrock | Espera; scope+intent+sql son 3 llamadas al modelo |
| Puerto 8000 ocupado | Un uvicorn viejo sigue vivo | Cierra esa terminal o `pkill -f uvicorn` |

---

## Referencia — datos de conexión actuales

| Qué | Valor |
|---|---|
| Modelo | Claude Sonnet 4.6 (ARN inference profile, cuenta 319797801226) |
| Alternativa que funciona | `amazon.nova-pro-v1:0` |
| Postgres host / puerto | `127.0.0.1` / `5434` (Docker `postgres-db`) |
| BD / esquema | `postgres` / `public` |
| Usuario / password | `admin` / `admin123` (solo local, no commitear) |
| Rango de datos | 2023-05-15 a 2026-01-05 |

> La contraseña es de desarrollo local. No la subas a git ni a ningún archivo versionado
> en un entorno real; aquí se documenta solo porque es una BD desechable de desarrollo.
