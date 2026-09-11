import requests
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct


client = QdrantClient(url="http://localhost:6333")

if not client.collection_exists(collection_name="demo"):
    client.create_collection(
        collection_name="demo",
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
    )

# dummy_data = [
#     "joao",
#     "Joao ama isabela",
#     "Laila ama Joao"
# ]

def generate_response(prompt:str):
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model":"mistral:7b-instruct-q4_K_M",
            "prompt":prompt,
            "stream": False
        }  
    )
    return response.json()["response"]

def main():
    # for i, text in enumerate(dummy_data):
    #     response = requests.post("http://localhost:11434/api/embed",
    #                 json={"model": "mxbai-embed-large:335m","input":"My name is Joao"},
    #                 )
    #     data = response.json()
    #     embbed = data['embeddings'][0]
    #     client.upsert(
    #         collection_name="demo",
    #         wait=True,
    #         points=[PointStruct(id=i,vector=embbed, payload={"text":text})]
    #     )

    prompt = input("Enter a prompt: ")
    adjusted_prompt = f"Representa esta sentença buscando por passagens relevantes: {prompt}"
    response = requests.post("http://localhost:11434/api/embed",
                json={"model": "mxbai-embed-large:335m","input": adjusted_prompt},
                )
    data = response.json()
    embbed = data['embeddings'][0]
    search_result = client.query_points(
        collection_name="demo",
        query=embbed,
        with_payload=True,
        limit=2  # limite de busca, busca as 3 sentenças mais relevantes
    ).points

    passagens_relevantes = "\n".join([f"- {point.payload['text']}" for point in search_result])
    augmented_prompt = f"""
        Passagens relevantes: {passagens_relevantes}
        Para responder a questão: {prompt}
    """
    
    response = generate_response(prompt)
    print(response)

if __name__ == "__main__":
    main()