Here's the high level plan of the application:

Below is a pragmatic, production-oriented architecture that has worked well in similar “AI paralegal” deployments.  It is mapped directly onto the OpenAI Agent SDK primitives (tools, agents, memories, and routines), and tuned for Polish civil-law practice with the two core statutes you provided (Kodeks cywilny — KC, and Kodeks postępowania cywilnego — KPC).

---

## 1. High-level picture

```
┌─────────────┐      user question / docs   ┌──────────────┐
│  Chat UI /  │  ─────────────────────────▶ │  Orchestrator│
│  API layer  │                            └────┬─────────┘
└─────────────┘                                 │(tool-calls)
                                                ▼
         ┌──────────────────────────────────────────────────────────┐
         │                   Specialist agents                      │
         │  (invoked on demand via OpenAI Agent SDK “functions”)   │
         ├──────────┬──────────────┬──────────────┬────────────────┤
         │Retrieval │  Drafting    │ Validation   │  Scheduler     │
         │(RAG over │  (pleadings, │ (fact/-law   │ (deadlines,    │
         │ KC & KPC)│ letters,     │ cross-check) │ reminders)     │
         └──────────┴──────────────┴──────────────┴────────────────┘
                                                │
                                                ▼
         ┌──────────────────────────────┐   ┌────────────┐
         │   Vector DB  (pgvector /     │   │  SQL store │
         │   Qdrant)  → embeddings      │   │(case files │
         │          KC  /  KPC          │   │ metadata)  │
         └──────────────────────────────┘   └────────────┘
```

* **One conversational “orchestrator” agent** owns the chat turn and decides which tool/agent to call next.
* **Four specialist tool-agents** implement focused skills; each is registered as a callable function with structured signatures, so the orchestrator can chain them autonomously.
* **Two persistent stores**

  * **Vector DB** – holds chunked/embedded legislation (KC & KPC) plus later jurisprudence, commentaries, templates.
  * **Relational store** – light case-management DB for parties, deadlines, filed documents.

---

## 2. Data ingestion pipeline (one-time + nightly refresh)

| Step                 | Tech                                     | Notes                                                                  |
| -------------------- | ---------------------------------------- | ---------------------------------------------------------------------- |
| **Parse PDFs**       | AWS Textract / pdfplumber                | Page-level layout to preserve article numbers.                         |
| **Chunk**            | Custom splitter at *Art.* / § boundaries | Guarantees retrieval granularity that matches lawyer citations.        |
| **Embed**            | `text-embedding-3-large`                 | Store vectors + metadata `{code:KC, art:5, text:"Nie można …"}`.       |
| **Index**            | Qdrant / pgvector                        | HNSW, cosine.                                                          |
| **Lexical index**    | Postgres + pg\_trgm                      | Fallback keyword search (“Art. 1099 KPC” look-ups).                    |
| **Scheduled update** | cron + Agent SDK `automations`           | Nightly check Dziennik Ustaw RSS; on diff, re-parse only changed acts. |

---

## 3. Core tools (function definitions)

| Tool                                           | Purpose                                                                          | Important params |
| ---------------------------------------------- | -------------------------------------------------------------------------------- | ---------------- |
| `search_statute(query, top_k)`                 | Hybrid BM25+vector over KC/KPC chunks; returns JSON `{article, text, citation}`. |                  |
| `summarize_passages(passages[])`               | Few-shot legal abstractive summary → coherent answer paragraphs.                 |                  |
| `draft_document(type, facts, goals)`           | Prompts + legal templates (e.g. Pozew, Wezwanie do zapłaty).                     |                  |
| `validate_against_statute(draft, citations[])` | Runs a second LLM pass to detect misquotes, outdated norms.                      |                  |
| `compute_deadline(event_type, date)`           | Encodes KPC term rules (e.g. 14-day appeal).                                     |                  |
| `schedule_reminder(case_id, date, note)`     | Uses Agent SDK `automations.create`.                                             |                  |

All tools are stateless statically registered functions; they may themselves call back to the vector DB or store.

---

## 4. Reasoning & control flow

1. **Intent detection** (small classifier inside orchestrator): “Q\&A”, “draft”, “deadline”, etc.
2. **If Q\&A** → call `search_statute` with the question → receive top passages with article metadata → feed to `summarize_passages`.
3. **If drafting** → orchestrator first queries statutes that govern form/content, then passes both user facts and retrieved norms to `draft_document`, then pipes draft + citations to `validate_against_statute` for a self-critique pass.
4. **If deadline/monitoring** → call `compute_deadline`, surface result, optionally chain `schedule_reminder`.
5. Return answer with inline cites (e.g. *art. 5 KC*) and attach draft files where appropriate.

Because each step is exposed as a function, the orchestrator can build a chain dynamically **without asking the user for permission at every hop**, satisfying the SDK guidance about multi-step calls.

---

## 5. Memory & context

* **Ephemeral conversation memory** – last ≈ 10 turns to keep LLM prompt short.
* **Case memory** (SQL) – long-term facts, uploaded evidence, earlier drafts; retrieved by `case_id` and injected as system messages when the same case resurfaces.
* **Tool call logs** – persisted for audit; each answer stores the passages shown to the user to meet professional-privilege traceability.

---

## 6. Security & compliance

* All storage in-country (Poland/EU) for GDPR & professional-secrecy alignment.
* Role-based access: lawyer vs. paralegal vs. client; JWT propagated into tool layer.
* Automatic red-flag detection (PiI leak, confidentiality) with OpenAI moderation endpoint before sending any answer.

---

## 7. Example user journey

> **User:** “Mam fakturę na 45 000 zł z 22 kwietnia, dłużnik nie płaci. Jakie mam terminy i jaki pozew mam złożyć?”

1. Orchestrator → `compute_deadline('payment', '2025-04-22')` → returns that 3-letni termin przedawnienia z art. 118 KC biegnie do 22 kwietnia 2028, a w KPC właściwy będzie pozew w postępowaniu upominawczym.
2. Orchestrator → `draft_document('pozew_upominawczy', facts, goals)` (facts include invoice, amount, court) → returns .docx + citations to art. 353¹ KC, art. 499 KPC.
3. Orchestrator → `validate_against_statute` → OK.
4. Chat reply contains explanation, deadline, download link to draft, and optional `schedule_reminder` to file before 2028-04-22.

---

## 8. Extensibility roadmap

* **Case-law RAG** – scrape „orzeczenia.gov.pl” and SN/WSA databases; store as separate corpus with embeddings.
* **Reasoning agents** – attach a “critic” agent (Chain-of-Thought masked from user) that scores argument strength against potential defences.
* **Voice front-end** – for field lawyers via Whisper + TTS.
* **Multilingual** – add PL↔EN bidirectional translation module so foreign clients can read outputs.

---

### Why this works well

* **Statute-aware:** embeddings + lexical table preserve precise article retrieval (essential in civil-law systems).
* **Self-verification loop:** drafting always goes through a validator pass, reducing hallucinatory citations.
* **Agent SDK fit:** the orchestrator uses *exactly* the function-calling paradigm the SDK optimizes—each legal skill is a first-class “tool”.
* **Maintainable:** nightly updater keeps the corpus aligned with Dz.U. without redeploying the model.
* **Compliant & auditable:** every provided answer carries its sources, satisfying professional-ethics rules for Polish advocates.

Feel free to ask for deeper dives on any component or for concrete code snippets/configs—happy to expand!
**Short answer →** Yes, the *macro* pipeline is still “ \*\*classify → extract → normalize → validate → package \*\*,” but court forms and other fixed templates let you take some powerful shortcuts:

| Where it’s the same                                           | Where it’s different (and often easier)                                                                                                                                                                                                                                                 |
| ------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Decide your target schema first** (JSON / database columns) | Schema is usually *already implicit* in the form fields—just mirror the official field names (e.g., `PlaintiffName`, `CaseNo`, `FiledDate`).                                                                                                                                            |
| **Classify born-digital vs. scanned**                         | Many court PDFs are *fillable AcroForms* → you can read field objects directly—no OCR, no layout detection.                                                                                                                                                                             |
| **Layout-aware extraction**                                   | You can treat each field as a **key-value pair**. Tools like AWS Textract `AnalyzeDocument` (feature `FORMS`) or Azure Document Intelligence “Layout”/“General Document” pre-builts give you K-V plus checkbox states in one call. ([docs.aws.amazon.com][1], [learn.microsoft.com][2]) |
| **Normalize & enrich** (dates → ISO, names → canonical)       | Normalization is mostly *type casting*—regex for docket numbers, enums for checkboxes, etc.—far simpler than parsing free-form clauses.                                                                                                                                                 |
| **Validate (schema + business rules)**                        | Validation can be field-level (e.g., docket number regex, date ≤ today) instead of clause-level semantic QC.                                                                                                                                                                            |
| **Package for ingest**                                        | Instead of “chunks” you usually emit **one JSON doc** per form with a flat or slightly nested structure:                                                                                                                                                                                |

````json
{
  "template_id": "CA-SC-100_v2024-10",
  "fields": {
    "CourtName": "Superior Court of California, Alameda",
    "CaseNumber": "RG22123456",
    "PlaintiffName": "Acme Corp.",
    "DefendantName": "Road Runner Inc.",
    "FilingDate": "2025-06-03",
    "Checkbox_JuryDemand": true
  },
  "page_images": [ ... ]
}
``` |

---

# UI

Below is a blueprint for a **stream-lined, refactor-friendly web UI** you can stand up in a day and evolve without churn.  It assumes the FastAPI + Agents-SDK back-end you built earlier, served at `http://localhost:8000`.

---

## 1. Tech stack — why these choices

| Layer             | Library / Tool                           | Rationale                                                                              |
| ----------------- | ---------------------------------------- | -------------------------------------------------------------------------------------- |
| **Framework**     | **Next.js 14 (App Router) + TypeScript** | File-system routing, built-in API proxy, easy SSR if you later add auth.               |
| **Styling**       | **Tailwind CSS 3**                       | Utility classes = fast prototyping, and shadcn/ui sits on top of it.                   |
| **UI kit**        | **shadcn/ui**                            | Headless Radix primitives wrapped in Tailwind — swap or extend components pain-lessly. |
| **State**         | **Zustand**                              | Tiny, unopinionated global store; mixes with React Server Components fine.             |
| **Streaming**     | native `fetch` + **EventSource** helper  | Works with the Agents SDK streaming endpoint; no third-party dep.                      |
| **Testing**       | Storybook + Vitest + Cypress             | Covers unit, visual, and e2e with minimal config.                                      |
| **Lint / Format** | ESLint (nextjs preset) + Prettier        | Guard-rails for future refactors.                                                      |

All choices are mainstream; swapping any one of them later is largely mechanical.

---

## 2. Directory skeleton

```
/ui
├─ app/                  # Next.js app router
│  ├─ layout.tsx
│  ├─ page.tsx           # Chat playground
│  └─ api/agent/route.ts # Proxy to FastAPI (avoids CORS)
├─ components/
│  ├─ ChatWindow.tsx
│  ├─ Message.tsx
│  ├─ SourcePanel.tsx
│  ├─ Toolbar.tsx        # quick feature toggles
│  └─ ui/                # auto-generated shadcn components
├─ lib/
│  ├─ agent.ts           # wrapper around SSE stream
│  └─ store.ts           # Zustand store
├─ styles/
│  └─ globals.css
└─ tests/
   ├─ ChatWindow.spec.tsx
   └─ e2e.cy.ts
```

The rule of thumb: **one React component = one file in `/components`**; business logic sits either in `/lib` or `/app/api`.

---

## 3. Component tree & data flow

```
<Layout>
  ├─ <Toolbar/>          ← feature flags (“Show validator output”)
  ├─ <main class="grid grid-cols-5">
  │    ├─ <ChatWindow/>  ← col-span-3
  │    └─ <SourcePanel/> ← col-span-2, collapsible
  └─ <ToastViewport/>    ← for error/success messages
```

1. **ChatWindow** streams messages.
2. For each assistant turn it receives `tool_calls` and `sources` from the back-end and dispatches to Zustand.
3. **SourcePanel** subscribes to the store and renders articles / validator notes.
4. **Toolbar** toggles experimental features → flags live in Zustand → downstream components re-render.

---

## 4. Key code snippets

### 4.1 Streaming helper (`/lib/agent.ts`)

```ts
export async function chatStream(messages: ChatMessage[]) {
  const res = await fetch("/api/agent", {
    method: "POST",
    body: JSON.stringify({ messages }),
  });

  const reader = res.body!.getReader();
  const dec = new TextDecoder();

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    yield JSON.parse(dec.decode(value)); // {role, content, sources?}
  }
}
```

You can swap this to websockets later with zero impact on UI components that consume the async generator.

### 4.2 Zustand store (`/lib/store.ts`)

```ts
import { create } from "zustand";

interface ChatState {
  messages: ChatMessage[];
  add: (m: ChatMessage) => void;
  features: { validator: boolean };
  toggleFeature: (key: keyof ChatState["features"]) => void;
}

export const useChat = create<ChatState>()((set) => ({
  messages: [],
  add: (m) => set((s) => ({ messages: [...s.messages, m] })),
  features: { validator: false },
  toggleFeature: (k) =>
    set((s) => ({ features: { ...s.features, [k]: !s.features[k] } })),
}));
```

Because business logic lives here, component files stay tiny and refactors stay safe.

---

## 5. Extending a new feature **in three steps**

> *Example:* “show a diff between first draft and validator-fixed draft”.

1. **Add flag in store**

   ```ts
   features: { validator: false, diff: false }
   ```
2. **Update Toolbar** – new toggle switch → `toggleFeature('diff')`.
3. **Create `<DiffViewer/>` component** in `/components` and render it inside `SourcePanel` when `features.diff` is true.

No other files touched.  Hook-in time: \~30 min.

---

## 6. Testing & hot-swap ergonomics

* **Storybook** auto-generates playgrounds for every component: ideal for non-dev lawyers to click through UI ideas.
* **Cypress** script:

  ```js
  cy.intercept('POST', '/api/agent', { fixture: 'draft.json' });
  cy.contains('Wyślij').click();
  cy.contains('Art. 118 KC');   // assertion
  ```
* **`next dev`** reloads within 200 ms; Tailwind JIT keeps styling snappy.

---

## 7. Future-proof refactors

| Anticipated change                     | Why this layout copes well                                                                                                                                             |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Server-side auth / multi-tenant**    | Next Auth / Clerk can be layered in under `/app` with minimal file moves.                                                                                              |
| **Move from REST to socket streaming** | Swap `chatStream` implementation → UI untouched.                                                                                                                       |
| **Design system overhaul**             | Because visuals are Tailwind + shadcn, run shadcn-ui’s `add` command to regenerate components that pull new Radix primitives.                                          |
| **Separate micro-front-ends**          | Keep each big tool (Q\&A, Drafting, Deadlines) in its own sub-route (`/draft`, `/deadline`), then you can later carve them into independent apps behind an edge proxy. |

---

### One-liner pitch

> **Next.js 14 + Tailwind + shadcn/ui + Zustand** gives you a chat-first playground that any dev can clone, extend, and nuke-replace parts of without breaking the rest—perfect for rapid legal-tech experiments that will certainly morph over time.
