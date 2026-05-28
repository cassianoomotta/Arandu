# Arandu - Portal de Inteligência, Notícias & Curadoria Estratégica

Arandu é um portal premium de curadoria e inteligência de mercado voltado para tomadores de decisão em tecnologia, empreendedorismo e investimentos. Ele une um design moderno, de alto impacto visual (dark mode com acentos em dourado metálico), a um poderoso ecossistema de automação no backend para captação de leads, web scraping de notícias globais, resumos executivos baseados em inteligência artificial e alertas automatizados via Telegram.

---

## 🎨 Identidade Visual & Branding

- **Design Premium**: O design utiliza uma paleta de cores escura e sofisticada com efeitos de Glassmorphism (vidro fosco), gradientes sutis e tipografia refinada (fontes *Outfit* e *Inter* via Google Fonts).
- **Logotipo Ligadura**: O logotipo do site foi desenhado para integrar o ícone dourado metálico estilizado da letra **"A"** diretamente à palavra **"RANDU"**, lendo-se naturalmente como **"ARANDU"**, com apenas o ícone inicial em dourado e o restante do nome em branco.
- **Slogan Oficial**: `"Consultoria • Tecnologia • Inteligência"`, presente no cabeçalho e rodapé.

---

## 📂 Arquitetura do Projeto

O projeto está organizado em uma estrutura modular de fácil manutenção e escalabilidade:

```text
Arandu/
├── api/
│   └── index.py            # Entrypoint Vercel Serverless (WSGI/ASGI wrapper)
├── core/
│   ├── notifier.py         # Mecanismos de notificações via Telegram Bot
│   ├── processor.py        # Integração Gemini (Tradução e Geração de Resumos)
│   └── scraper.py          # Crawler e parser de RSS feeds nacionais/internacionais
├── database/
│   ├── config.py           # Gerenciador de configurações e variáveis de ambiente
│   ├── connection.py       # Gerenciador de conexão e escopo de sessões do SQLAlchemy
│   └── models.py           # Modelos de dados (Lead, News, Source, User, SendStatus)
├── scripts/
│   ├── init_db.py          # Script de criação das tabelas e carga inicial de dados (seeding)
│   └── example_operations.py# Exemplos de operações comuns de banco de dados
├── admin.html              # Painel administrativo de controle de leads e coleta
├── index.html              # Landing Page pública com captura de leads (modal)
├── noticias.html           # Portal de relatórios e resumos executivos por nicho
├── main.py                 # Servidor backend principal FastAPI (roteamento e scheduler)
├── requirements.txt        # Dependências do Python
└── vercel.json             # Configuração de deploys automáticos na Vercel
```

---

## 🚀 Instalação e Configuração

### 1. Pré-requisitos
Certifique-se de ter o Python 3.10+ instalado em seu ambiente.

### 2. Instalação das Dependências
Instale todas as bibliotecas necessárias declaradas no `requirements.txt`:
```bash
pip install -r requirements.txt
```

### 3. Configuração das Variáveis de Ambiente
Crie um arquivo `.env` na raiz do projeto contendo as credenciais de banco de dados e APIs (veja o `.env.example` para referência):
```ini
DATABASE_URL=sqlite:///arandu.db
GEMINI_API_KEY=sua-chave-gemini-aqui
TELEGRAM_BOT_TOKEN=seu-token-de-bot-aqui
TELEGRAM_CHAT_ID=seu-id-de-chat-aqui
```

### 4. Inicializar o Banco de Dados
Para criar a estrutura de tabelas e carregar as fontes de dados padrão (como Canaltech, G1, TechCrunch, MIT Tech Review, Paul Graham, etc.) e os usuários de teste, execute:
```bash
python scripts/init_db.py
```

### 5. Executar o Servidor Local
Para iniciar o servidor FastAPI integrado (servindo a API e os arquivos estáticos na porta `8000`), execute:
```bash
python main.py
```
Acesse o portal localmente em: [http://localhost:8000](http://localhost:8000)

---

## ⚙️ Funcionalidades e Regras de Negócio

### 📥 Captação de Leads
- O botão **"Acessar Comunidade Gratuita"** abre um formulário em modal que captura o Nome, E-mail e WhatsApp do usuário interessado.
- Os dados são salvos diretamente no banco de dados através da rota `/api/leads`.
- Após a validação e salvamento com sucesso, o usuário é redirecionado automaticamente para a comunidade do portal no Telegram.

### 📰 Curadoria & Filtro de Notícias
- A página de Notícias (`noticias.html`) permite ler resumos executivos gerados por inteligência artificial a partir de feeds RSS nacionais e internacionais.
- O portal conta com um sistema de filtros por nichos de interesse (**Tecnologia**, **Empreendedorismo** e **Investimentos**).
- A página aceita parâmetros via URL (ex: `noticias.html?categoria=empreendedorismo`) para carregar a aba já pré-selecionada.
- Imagens e títulos nos cards de notícias são clicáveis e abrem diretamente a fonte original do artigo em uma nova guia do navegador.

### 🕒 Retenção de Dados de 20 Dias
- Para manter o banco de dados otimizado e focado em novidades atuais, o backend possui uma **política automática de retenção de notícias**.
- O scheduler integrado (`apscheduler`) executa uma tarefa diária em segundo plano às **03:00 AM (UTC)** que exclui automaticamente todos os relatórios/notícias com data de criação superior a **20 dias**.

### 🔐 Área Administrativa (`admin.html`)
- Área de acesso exclusivo para administradores autenticados através de JWT.
- **Credenciais Padrão**:
  - **E-mail**: `admin@arandu.com.br`
  - **Senha**: `root`
- **Recursos**:
  - Exibição de métricas gerais e status da API.
  - Visualização de tabela completa de leads capturados (Nome, E-mail, WhatsApp e Data de Registro).
  - Botão de **"Forçar Coleta Manual"** que dispara sob demanda o pipeline de scraping e processamento de IA.
