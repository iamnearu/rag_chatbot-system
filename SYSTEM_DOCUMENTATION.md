# EOV COPILOT DEMO
## Tài Liệu Mô Tả Hệ Thống

## Mục Lục

1. [Tổng Quan Hệ Thống](#1-tổng-quan-hệ-thống)
2. [Kiến Trúc Microservice](#2-kiến-trúc-microservice)
3. [Thiết Kế Chi Tiết Từng Service](#3-thiết-kế-chi-tiết-từng-service)
4. [Công Nghệ Sử Dụng](#4-công-nghệ-sử-dụng)
5. [Kế Hoạch Xây Dựng](#5-kế-hoạch-xây-dựng)
6. [Yêu Cầu Đạt Được](#6-yêu-cầu-đạt-được)
7. [Tiêu Chí Đánh Giá](#7-tiêu-chí-đánh-giá)
8. [Phương Pháp Đánh Giá](#8-phương-pháp-đánh-giá)
9. [Dữ Liệu Demo & Test](#9-dữ-liệu-demo--test)

---

## 1. Tổng Quan Hệ Thống

### 1.1 Mục Tiêu

EOV COPILOT DEMO là nền tảng AI thông minh cho bảo trì công nghiệp, bao gồm:

- **EOV CoPilot**: RAG-based chatbot agent hỗ trợ tra cứu tài liệu kỹ thuật
- **EOV Predict™**: Module AI dự báo hư hỏng 

### 1.2 High-Level Architecture

```mermaid
graph TB
    subgraph "Client Layer"
        WEB[Web Browser]
        MOBILE[Mobile App]
    end

    subgraph "Presentation Layer"
        FE[Next.js Frontend<br/>Port 3000]
    end

    subgraph "API Gateway"
        GW[Traefik Gateway<br/>Port 80/443]
    end

    subgraph "Service Layer"
        OCR[OCR Service<br/>:8001]
        DOC[Doc Processing<br/>:8002]
        EMB[Embedding Service<br/>:8003]
        KG[KG Service<br/>:8004]
        VEC[Vector Service<br/>:8005]
        RAG[RAG Engine<br/>:8006]
        LLM[LLM Gateway<br/>:8007]
        PRED[Predict Service<br/>:8008]
    end

    subgraph "Data Layer"
        PG[(PostgreSQL<br/>+ pgvector)]
        NEO[(Neo4j<br/>Graph DB)]
        REDIS[(Redis<br/>Cache)]
        MINIO[(MinIO<br/>Object Storage)]
        MQ[RabbitMQ<br/>Message Queue]
    end

    subgraph "External"
        OLLAMA[Ollama LLM]
        OPENAI[OpenAI API]
    end

    WEB --> FE
    MOBILE --> FE
    FE --> GW
    GW --> OCR
    GW --> RAG
    GW --> PRED
    
    OCR --> MQ
    MQ --> DOC
    DOC --> EMB
    DOC --> KG
    EMB --> VEC
    
    VEC --> PG
    KG --> NEO
    RAG --> VEC
    RAG --> KG
    RAG --> LLM
    
    LLM --> OLLAMA
    LLM --> OPENAI
    
    OCR --> MINIO
    RAG --> REDIS
```

---

## 2. Kiến Trúc Microservice

### 2.1 Service Communication Diagram

```mermaid
flowchart LR
    subgraph "Ingestion Flow"
        A[Upload PDF] --> B[OCR Service]
        B -->|RabbitMQ| C[Doc Processing]
        C --> D[Chunking]
        D -->|Parallel| E[Embedding Service]
        D -->|Parallel| F[KG Service]
    end

    subgraph "Storage Flow"
        E --> G[Vector Service]
        G --> H[(pgvector)]
        F --> I[(Neo4j)]
    end

    subgraph "Query Flow"
        J[User Query] --> K[RAG Engine]
        K --> L[Query Embedding]
        L --> M[Vector Search]
        M --> H
        K --> N[Graph Query]
        N --> I
        K --> O[Reranking]
        O --> P[LLM Gateway]
        P --> Q[Response]
    end
```

### 2.2 Event-Driven Architecture

```mermaid
sequenceDiagram
    participant User
    participant OCR as OCR Service
    participant MQ as RabbitMQ
    participant DocProc as Doc Processing
    participant Embed as Embedding
    participant KG as KG Service
    participant Vec as Vector Service

    User->>OCR: Upload Document
    OCR->>OCR: Extract Text (DeepSeek-OCR)
    OCR->>MQ: Publish: document.processed
    
    MQ->>DocProc: Consume: document.processed
    DocProc->>DocProc: Chunking (StyleDFS)
    DocProc->>MQ: Publish: document.chunked
    
    par Parallel Processing
        MQ->>Embed: Consume: document.chunked
        Embed->>Embed: Generate Embeddings
        Embed->>Vec: Store Vectors
    and
        MQ->>KG: Consume: document.chunked
        KG->>KG: Extract Entities
        KG->>KG: Build Graph
    end
```

### 2.3 Data Flow Diagram

```mermaid
flowchart TD
    subgraph "Input Sources"
        PDF[PDF Documents]
        IMG[Scanned Images]
        TXT[Text Files]
    end

    subgraph "Processing Pipeline"
        OCR_PROC[OCR Processing<br/>DeepSeek-OCR / Tesseract]
        CHUNK[Chunking<br/>StyleDFS / Semantic]
        EMBED_PROC[Embedding<br/>bge-m3]
        ENTITY[Entity Extraction<br/>Rule-based / NER]
    end

    subgraph "Storage"
        MARKDOWN[Markdown Content]
        CHUNKS[Document Chunks]
        VECTORS[Vector Embeddings]
        GRAPH[Knowledge Graph]
    end

    subgraph "Retrieval"
        VEC_SEARCH[Vector Search<br/>Cosine Similarity]
        GRAPH_SEARCH[Graph Query<br/>Cypher]
        FUSION[Fusion & Reranking<br/>RRF Algorithm]
    end

    subgraph "Generation"
        CONTEXT[Context Assembly]
        LLM_GEN[LLM Generation<br/>Llama 3.1 / GPT]
        RESPONSE[Final Response]
    end

    PDF --> OCR_PROC
    IMG --> OCR_PROC
    TXT --> CHUNK
    
    OCR_PROC --> MARKDOWN
    MARKDOWN --> CHUNK
    CHUNK --> CHUNKS
    
    CHUNKS --> EMBED_PROC
    CHUNKS --> ENTITY
    
    EMBED_PROC --> VECTORS
    ENTITY --> GRAPH
    
    VECTORS --> VEC_SEARCH
    GRAPH --> GRAPH_SEARCH
    
    VEC_SEARCH --> FUSION
    GRAPH_SEARCH --> FUSION
    
    FUSION --> CONTEXT
    CONTEXT --> LLM_GEN
    LLM_GEN --> RESPONSE
```

---

## 3. Thiết Kế Chi Tiết Từng Service

### 3.1 OCR Service

```mermaid
flowchart TB
    subgraph "OCR Service [:8001]"
        API[FastAPI Endpoints]
        UPLOAD["/upload"]
        STATUS["/status/{job_id}"]
        DOCS["/documents"]
        
        subgraph "Processing"
            VALID[File Validation]
            DEEPSEEK[DeepSeek-OCR]
            TESSERACT[Tesseract OCR<br/>Fallback]
            POSTPROC[Post Processing]
        end
        
        subgraph "Storage"
            MINIO_UP[MinIO Upload]
            DB_SAVE[Database Save]
        end
        
        subgraph "Events"
            EVENT_PUB[RabbitMQ Publisher]
        end
    end

    API --> UPLOAD
    API --> STATUS
    API --> DOCS
    
    UPLOAD --> VALID
    VALID --> DEEPSEEK
    DEEPSEEK -.->|Error| TESSERACT
    DEEPSEEK --> POSTPROC
    TESSERACT --> POSTPROC
    
    POSTPROC --> MINIO_UP
    POSTPROC --> DB_SAVE
    DB_SAVE --> EVENT_PUB
```

**Endpoints:**
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/ocr/upload` | Upload document |
| GET | `/api/v1/ocr/status/{job_id}` | Check job status |
| GET | `/api/v1/ocr/documents` | List documents |
| GET | `/api/v1/ocr/documents/{id}` | Get document |
| DELETE | `/api/v1/ocr/documents/{id}` | Delete document |

---

### 3.2 Document Processing Service

```mermaid
flowchart TB
    subgraph "Doc Processing Service [:8002]"
        CONSUME[RabbitMQ Consumer]
        
        subgraph "Chunking Strategies"
            STYLEDFS[StyleDFS Chunker<br/>Structure-aware]
            SEMANTIC[Semantic Chunker<br/>Embedding-based]
            FIXED[Fixed Size Chunker<br/>Simple split]
        end
        
        subgraph "Processing"
            PARSE[Markdown Parser]
            DETECT[Structure Detection]
            SPLIT[Text Splitting]
            META[Metadata Extraction]
        end
        
        OUTPUT[Chunks Output]
        PUBLISH[Event Publisher]
    end

    CONSUME --> PARSE
    PARSE --> DETECT
    DETECT --> STYLEDFS
    DETECT --> SEMANTIC
    DETECT --> FIXED
    
    STYLEDFS --> SPLIT
    SEMANTIC --> SPLIT
    FIXED --> SPLIT
    
    SPLIT --> META
    META --> OUTPUT
    OUTPUT --> PUBLISH
```

**Chunking Strategies:**
| Strategy | Use Case | Chunk Size |
|----------|----------|------------|
| StyleDFS | Structured docs (headers, tables) | Variable |
| Semantic | Long paragraphs | 500-1000 tokens |
| Fixed | Simple text | 1000 chars |

---

### 3.3 Embedding Service

```mermaid
flowchart TB
    subgraph "Embedding Service [:8003]"
        API[FastAPI Endpoints]
        
        subgraph "Model Layer"
            LOAD[Model Loader]
            BGE[BAAI/bge-m3<br/>1024 dimensions]
            CACHE[Model Cache]
        end
        
        subgraph "Processing"
            BATCH[Batch Processing]
            ENCODE[Text Encoding]
            NORM[Normalization]
        end
        
        OUTPUT[Vector Output]
        VEC_SVC[Vector Service]
    end

    API --> BATCH
    LOAD --> BGE
    BGE --> CACHE
    
    BATCH --> ENCODE
    CACHE --> ENCODE
    ENCODE --> NORM
    NORM --> OUTPUT
    OUTPUT --> VEC_SVC
```

**Model Specifications:**
| Parameter | Value |
|-----------|-------|
| Model | BAAI/bge-m3 |
| Dimensions | 1024 |
| Max Sequence | 8192 tokens |
| GPU Required | Recommended |

---

### 3.4 Knowledge Graph Service

```mermaid
flowchart TB
    subgraph "KG Service [:8004]"
        API[FastAPI Endpoints]
        
        subgraph "Entity Extraction"
            PATTERN[Pattern Matching]
            NER[Named Entity Recognition]
            RELATION[Relation Extraction]
        end
        
        subgraph "Graph Operations"
            CREATE[Create Nodes]
            LINK[Create Relationships]
            QUERY[Cypher Queries]
        end
        
        NEO[(Neo4j Database)]
    end

    API --> PATTERN
    API --> QUERY
    
    PATTERN --> NER
    NER --> RELATION
    RELATION --> CREATE
    CREATE --> LINK
    LINK --> NEO
    
    QUERY --> NEO
```

**Entity Types:**
```mermaid
graph LR
    EQUIP[Equipment] -->|HAS_SYMPTOM| SYMP[Symptom]
    SYMP -->|CAUSED_BY| CAUSE[Cause]
    CAUSE -->|REQUIRES| SOL[Solution]
    SOL -->|NEEDS| PART[Part]
    EQUIP -->|FOLLOWS| PROC[Procedure]
```

---

### 3.5 Vector Service

```mermaid
flowchart TB
    subgraph "Vector Service [:8005]"
        API[FastAPI Endpoints]
        
        subgraph "Operations"
            UPSERT[Upsert Vectors]
            SEARCH[Similarity Search]
            DELETE[Delete Vectors]
        end
        
        subgraph "Search Algorithms"
            COSINE[Cosine Similarity]
            L2[L2 Distance]
            IP[Inner Product]
        end
        
        PG[(PostgreSQL<br/>+ pgvector)]
    end

    API --> UPSERT
    API --> SEARCH
    API --> DELETE
    
    SEARCH --> COSINE
    SEARCH --> L2
    SEARCH --> IP
    
    UPSERT --> PG
    COSINE --> PG
    L2 --> PG
    IP --> PG
```

**Index Configuration:**
| Parameter | Value |
|-----------|-------|
| Index Type | HNSW |
| Dimension | 1024 |
| Distance | Cosine |
| ef_construction | 128 |
| m | 16 |

---

### 3.6 RAG Engine Service

```mermaid
flowchart TB
    subgraph "RAG Engine [:8006]"
        API[FastAPI Endpoints]
        
        subgraph "Query Processing"
            PARSE_Q[Parse Query]
            EMBED_Q[Query Embedding]
            INTENT[Intent Detection]
        end
        
        subgraph "Retrieval"
            VEC_SEARCH[Vector Search]
            GRAPH_Q[Graph Query]
            RERANK[RRF Reranking]
        end
        
        subgraph "Generation"
            CTX_BUILD[Context Builder]
            PROMPT[Prompt Template]
            LLM_CALL[LLM Generation]
            STREAM[Response Streaming]
        end
    end

    API --> PARSE_Q
    PARSE_Q --> EMBED_Q
    EMBED_Q --> INTENT
    
    INTENT --> VEC_SEARCH
    INTENT --> GRAPH_Q
    
    VEC_SEARCH --> RERANK
    GRAPH_Q --> RERANK
    
    RERANK --> CTX_BUILD
    CTX_BUILD --> PROMPT
    PROMPT --> LLM_CALL
    LLM_CALL --> STREAM
```

**RAG Fusion Algorithm:**
```
RRF Score = Σ (1 / (k + rank_i))

where:
- k = 60 (constant)
- rank_i = position in each result list
```

---

### 3.7 LLM Gateway Service

```mermaid
flowchart TB
    subgraph "LLM Gateway [:8007]"
        API[FastAPI Endpoints]
        
        subgraph "Provider Abstraction"
            ROUTER[Provider Router]
            OLLAMA_C[Ollama Client]
            OPENAI_C[OpenAI Client]
        end
        
        subgraph "Features"
            STREAM[Streaming]
            RETRY[Retry Logic]
            FALLBACK[Fallback]
            RATE[Rate Limiting]
        end
        
        subgraph "Models"
            LLAMA[Llama 3.1 8B]
            QWEN[Qwen 2.5 7B]
            GPT[GPT-4 / GPT-3.5]
        end
    end

    API --> ROUTER
    ROUTER --> OLLAMA_C
    ROUTER --> OPENAI_C
    
    OLLAMA_C --> LLAMA
    OLLAMA_C --> QWEN
    OPENAI_C --> GPT
    
    ROUTER --> STREAM
    ROUTER --> RETRY
    RETRY --> FALLBACK
    ROUTER --> RATE
```

---

### 3.8 Predict Service

```mermaid
flowchart TB
    subgraph "Predict Service [:8008]"
        API[FastAPI Endpoints]
        
        subgraph "Prediction Models"
            XGB[XGBoost<br/>Failure Prediction]
            LGBM[LightGBM<br/>Delay Prediction]
            COX[CoxPH<br/>Survival Analysis]
        end
        
        subgraph "Features"
            FEAT_ENG[Feature Engineering]
            RISK[Risk Calculation]
            SCHEDULE[Schedule Optimization]
        end
        
        subgraph "Output"
            PROB[Failure Probability]
            SCORE[Risk Score]
            ALERT[Alert Generation]
        end
    end

    API --> FEAT_ENG
    FEAT_ENG --> XGB
    FEAT_ENG --> LGBM
    FEAT_ENG --> COX
    
    XGB --> PROB
    LGBM --> RISK
    COX --> SCHEDULE
    
    PROB --> SCORE
    SCORE --> ALERT
```

**Risk Level Classification:**
| Score Range | Level | Action |
|-------------|-------|--------|
| 70-100 | HIGH | Immediate action required |
| 40-69 | MEDIUM | Plan maintenance |
| 0-39 | LOW | Monitor |

---

## 4. Công Nghệ Sử Dụng

### 4.1 Backend Technologies

| Layer | Technology | Version | Purpose |
|-------|------------|---------|---------|
| **Runtime** | Python | 3.11 | Main programming language |
| **Framework** | FastAPI | 0.104+ | REST API framework |
| **ASGI** | Uvicorn | 0.24+ | ASGI server |
| **Validation** | Pydantic | 2.0+ | Data validation |
| **ORM** | SQLAlchemy | 2.0+ | Database ORM |
| **Async HTTP** | httpx | 0.25+ | HTTP client |

### 4.2 AI/ML Technologies

| Component | Technology | Purpose |
|-----------|------------|---------|
| **OCR** | DeepSeek-OCR | Document digitization |
| **OCR Fallback** | Tesseract | Backup OCR |
| **Embedding** | BAAI/bge-m3 | Text to vector |
| **LLM (Local)** | Ollama + Llama 3.1 | Text generation |
| **LLM (Cloud)** | OpenAI GPT | Alternative LLM |
| **ML** | XGBoost, LightGBM | Predictions |

### 4.3 Data Storage

| Type | Technology | Version | Purpose |
|------|------------|---------|---------|
| **Relational DB** | PostgreSQL | 16 | Primary database |
| **Vector DB** | pgvector | 0.7+ | Vector search |
| **Graph DB** | Neo4j | 5.15 | Knowledge graph |
| **Cache** | Redis | 7 | Session & cache |
| **Object Storage** | MinIO | Latest | File storage |
| **Message Queue** | RabbitMQ | 3 | Event messaging |

### 4.4 Frontend Technologies

| Technology | Version | Purpose |
|------------|---------|---------|
| Next.js | 14+ | React framework |
| TypeScript | 5+ | Type safety |
| TailwindCSS | 3+ | Styling |
| React | 18+ | UI library |



---

## 5. Kế Hoạch Xây Dựng

### 5.1 Timeline 


```mermaid
gantt
    title EOV COPILOT DEMO 4-Week Sprint Plan
    dateFormat  YYYY-MM-DD

    section Pharse 1
    Project Setup & Infra     :active, w1-1, 2025-12-23, 4d
    Database Schema           :w1-2, after w1-1, 2d
    OCR Service (API + Upload):w1-3, 2025-12-25, 5d

    section Pharse 2
    Doc Processing (chunking) :w2-1, 2025-12-30, 4d
    Embedding Service (API)   :w2-2, after w2-1, 4d
    Vector Service (pgvector) :w2-3, after w2-2, 3d

    section Pharse 3
    KG Service (entity + graph):w3-1, 2026-01-06, 4d
    RAG Engine (retrieval)    :w3-2, after w3-1, 4d
    LLM Gateway (provider)     :w3-3, 2026-01-08, 5d

    section Pharse 4
    Predict Service (models)  :w4-1, 2026-01-13, 4d
    Frontend: Chat UI + Dashboard :w4-2, 2026-01-13, 5d
    Testing           :w4-3, after w4-1, 4d

```

### 5.2 Milestones

| Week | Milestone | Status |
|------|-----------|--------|
| 1 | Foundation up + OCR basic | In progress |
| 2 | Doc pipeline + Embedding + Vector store | Planned |
| 3 | KG + RAG + LLM integration | Planned |
| 4 | Predict models + Frontend + Testing/Deploy | Planned |


### 5.3 Sprint Planning (4-week breakdown & task ownership)
Tuần 1
- [ ] Thiết lập dự án, repository
- [ ] Môi trường (tệp .env)
- [ ] OCR Service: endpoint upload, pipeline xử lý cơ bản

Tuần 2
- [ ] Xử lý tài liệu: chiến lược chia đoạn, hooks sự kiện
- [ ] Embedding Service: loader mô hình, API mã hóa
- [ ] Vector Service: schema pgvector, API upsert/search

Tuần 3
- [ ] KG Service: trích xuất thực thể và kết nối Neo4j
- [ ] RAG Engine: luồng truy vấn, hợp nhất vector + đồ thị
- [ ] LLM Gateway: trừu tượng hóa provider & streaming

Tuần 4
- [ ] Predict Service: pipeline đặc trưng và endpoint mô hình cơ bản
- [ ] Frontend: UI Chat + tích hợp tối thiểu Dashboard Predict
- [ ] Kiểm thử


---

## 6. Yêu Cầu Đạt Được

### 6.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | Upload và OCR tài liệu PDF/Image | High |  |
| FR-02 | Chunking thông minh giữ nguyên cấu trúc | High |  |
| FR-03 | Vector search với pgvector | High |  |
| FR-04 | Knowledge Graph với Neo4j | Medium |  |
| FR-05 | RAG query với streaming response | High |  |
| FR-06 | Multi-provider LLM support | Medium |  |
| FR-07 | Schedule optimization | Medium |  |
| FR-08 | Chat history | High |  |
---

## 7. Tiêu Chí Đánh Giá

### 7.1 AI Quality Metrics

| Metric | Evaluation Method |
|--------|-------------------|
| **OCR Accuracy** | Character Error Rate (CER) |
| **Retrieval Precision** | Manual annotation |
| **Retrieval Recall** | Manual annotation |
| **Answer Relevance** | Human evaluation |
| **Prediction Accuracy** | Cross-validation |
| **F1 Score (Failure)** | Test dataset |

---