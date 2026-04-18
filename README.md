# 🤖 InfoAgent: AI-Powered Daily Tech Briefing

InfoAgent is a smart information aggregation agent designed for developers and tech enthusiasts. It scrapes high-quality RSS feeds, uses LLMs (DeepSeek) to summarize key insights, and provides a RAG-based chat interface for deep-diving into specific articles.

## ✨ Features

- **Multi-Source Aggregation**: HN, Ars Technica, OpenAI, Hugging Face, etc.
- **AI-Driven Curation**: Summarizes daily news into structured "Vibe" overviews and key points.
- **Auto-Tagging**: Intelligent categorization of articles (e.g., #AI, #Security).
- **RAG Chat**: Ask follow-up questions about any article using vector-retrieval.
- **Glassmorphism UI**: Modern, dark-themed responsive dashboard.
- **Local Persistence**: Uses SQLite and ChromaDB for data and vector storage.

---

## 🚀 Quick Start (Dockerized) - Recommended

The simplest way to deploy InfoAgent is using Docker. This ensures all dependencies (including Redis) are correctly configured.

### Prerequisites
- [Docker](https://www.docker.com/) & [Docker Compose](https://docs.docker.com/compose/)
- A **DeepSeek API Key** (Get one at [deepseek.com](https://www.deepseek.com/))

### Steps
1.  **Clone the repository**:
    ```bash
    git clone https://github.com/your-username/InfoAgent.git
    cd InfoAgent
    ```
2.  **Configure environment**:
    Create a `.env` file in the root with your API key:
    ```bash
    DEEPSEEK_API_KEY="your_api_key_here"
    ```
3.  **Launch**:
    ```bash
    docker compose up -d
    ```
4.  **Access the Dashboard**:
    Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

---

## 🛠 Manual Setup (Local Development)

If you prefer to run it directly on your machine:

1.  **Create Virtual Environment**:
    ```bash
    python -m venv venv
    source venv/bin/activate  # Windows: venv\Scripts\activate
    ```
2.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Run Redis**:
    Ensure a Redis server is running at `localhost:6379`.
4.  **Launch Application**:
    - **Windows**: Use `Open_Web_Dashboard.bat`
    - **Standard**: `uvicorn main:app --reload`

---

## 🏗 Project Structure

- `app/api/`: API routes (Summary & RAG)
- `app/services/`: Core logic (LLM, RSS, DB, VectorStore)
- `app/models/`: SQLModel and Pydantic schemas
- `static/` & `templates/`: Frontend assets
- `chroma_db/`: Persistent vector storage
- `infoagent.db`: Main application database (SQLite)

## 📄 License
MIT
