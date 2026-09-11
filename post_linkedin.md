🇧🇷 Montei uma RAG simples pra me ajudar a ler os artigos da minha pesquisa.

 

O problema: tenho uma pilha de PDFs e vivo esquecendo qual deles disse o quê. Queria perguntar em linguagem normal e receber respostas presas a esses artigos, não ao que um chatbot lembra do treino.

 

Qdrant e Ollama, os dois rodando localmente. Nada sai da máquina e funciona offline. O Qdrant guarda os vetores. O Ollama serve dois modelos: o mxbai-embed-large transforma cada trecho em um vetor de 1024 dimensões e o Mistral 7B escreve as respostas. A extração de texto é com pypdf.

 

A parte que mais gostei é a ingestão. Um watcher observa uma pasta: jogo um PDF lá e em segundos o texto foi extraído, cortado em trechos de ~1200 caracteres com sobreposição, virou embedding e foi pro Qdrant. Editei o arquivo? Só ele é reindexado. Apaguei? Os vetores vão junto. O hash de cada arquivo fica salvo, então reiniciar não recalcula tudo.

 

Extrair texto de PDF acadêmico é a parte chata: duas colunas, cabeçalho em toda página e uma lista de referências que só atrapalha. Meu próprio artigo, exportado do Google Docs, veio com uma palavra por linha. O código de limpeza acabou maior que o da busca.

 

Precisava entender por que um método usa redução aleatória de dimensionalidade em vez de PCA. Perguntei e recebi os trechos exatos, com o nome do artigo de onde vieram. Em vez de reler três PDFs atrás de uma frase, li cinco parágrafos e já sabia onde procurar o resto.

 

. . .

 

🇺🇸 I built a simple RAG to help me read the papers for my research.

 

The problem: I have a pile of PDFs and I keep forgetting which one said what. I wanted to ask questions in plain language and get answers tied to those papers, not to whatever a chatbot remembers from training.

 

Qdrant and Ollama, both running locally. Nothing leaves the machine and it works offline. Qdrant holds the vectors. Ollama serves two models: mxbai-embed-large turns each chunk into a 1024-dimension vector and Mistral 7B writes the answers. Text extraction is pypdf.

 

The part I like most is ingestion. A watcher sits on a folder: I drop a PDF in and seconds later the text has been pulled, split into overlapping ~1200-character chunks, embedded and stored in Qdrant. Edit the file? Only that one is re-indexed. Delete it? Its vectors go too. Each file's hash is saved, so restarting doesn't re-embed everything.

 

Academic PDF extraction is the messy part: two columns, a header on every page, a reference list that mostly adds noise. My own paper, exported from Google Docs, came out one word per line. The cleanup code ended up longer than the retrieval.

 

I needed to understand why one method uses random dimensionality reduction instead of PCA. I asked, and got the exact passages back with the name of the paper they came from. Instead of rereading three PDFs hunting for one sentence, I read five paragraphs and knew where to look for the rest.
