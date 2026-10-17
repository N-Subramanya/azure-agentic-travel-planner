import os
import logging
from flask import Flask, request, render_template
from dotenv import load_dotenv

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient

from openai import AzureOpenAI

# Load env
load_dotenv()

app = Flask(__name__)

def get_env(name, default=None):
    value = os.getenv(name, default)
    if isinstance(value, str):
        return value.strip().strip('"').strip("'")
    return value

# -------------------------------
# Azure AI Search Config
# -------------------------------
search_endpoint = get_env('SEARCH_SERVICE_ENDPOINT')
search_key = get_env('SEARCH_SERVICE_QUERY_KEY')
search_index = get_env('SEARCH_INDEX_NAME')

# -------------------------------
# Azure OpenAI Config
# -------------------------------
openai_endpoint = get_env("AZURE_OPENAI_ENDPOINT")
openai_key = get_env("AZURE_OPENAI_KEY")
deployment_name = get_env("AZURE_OPENAI_DEPLOYMENT")

client = AzureOpenAI(
    api_key=openai_key,
    api_version="2024-02-01",
    azure_endpoint=openai_endpoint
)

# -------------------------------
# SEARCH FUNCTION
# -------------------------------
def search_query(query):
    credential = AzureKeyCredential(search_key)
    search_client = SearchClient(search_endpoint, search_index, credential)

    results = search_client.search(
        query,
        top=5,
        select=["chunk", "title", "metadata_storage_path"]
    )

    return list(results)


# -------------------------------
# LLM ANSWER FUNCTION
# -------------------------------
def generate_answer(query, search_results):

    # Build context from chunks
    context = ""
    sources = []

    for r in search_results:
        context += r["chunk"] + "\n\n"
        sources.append({
            "title": r["title"],
            "url": r["metadata_storage_path"]
        })

    prompt = f"""
You are a helpful assistant.

Answer the question ONLY using the context below.
If the answer is not present, say "I don't know based on the provided data."

Context:
{context}

Question:
{query}

Answer:
"""

    response = client.chat.completions.create(
        model=deployment_name,
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )

    answer = response.choices[0].message.content

    return answer, sources


# -------------------------------
# ROUTES
# -------------------------------
@app.route("/")
def home():
    return render_template("rag_home.html")
# @app.route("/")
# def home():
#     return "HOME PAGE WORKING"


@app.route("/health")
def health():
    return {"status": "ok"}


@app.route("/ask", methods=["GET"])
def ask():
    try:
        query = request.args["question"]

        # Step 1: Retrieve
        results = search_query(query)

        # Step 2: Generate
        answer, sources = generate_answer(query, results)

        return render_template(
            "rag_result.html",
            question=query,
            answer=answer,
            sources=sources,
            search_results=results
        )

    except Exception:
        logging.exception("Failed to answer question")
        return render_template(
            "error.html",
            error_message="Something went wrong while answering your question. Please try again."
        ), 500


# -------------------------------
if __name__ == "__main__":
    app.run()