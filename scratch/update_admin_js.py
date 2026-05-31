import os

file_path = r"c:\Users\Cassiano\OneDrive\Documentos\Antigravity\Projetos\Arandu\admin.html"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Define target
target = """        async function triggerManualPipeline() {
            if (!token) return;
            const triggerBtn = document.getElementById("triggerPipelineBtn");
            
            // Optimistic UI disable
            triggerBtn.disabled = true;
            triggerBtn.innerHTML = `
                <svg class="animate-spin h-4 w-4 text-black inline-block" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <span>Enviando Comando...</span>
            `;

            // Start polling immediately so the UI catches the status transition to "running"
            startPipelinePolling();

            try {
                const response = await fetch(`${API_BASE_URL}/api/admin/coleta-manual`, {
                    method: "POST",
                    headers: {
                        "Authorization": `Bearer ${token}`
                    }
                });

                if (response.ok) {
                    showToast("Pipeline Concluído", "A curadoria de notícias e processamento com IA foi concluído com sucesso!", "success");
                } else {
                    const data = await response.json();
                    showToast("Falha no Pipeline", data.detail || "Erro inesperado ao executar o pipeline.", "error");
                }
            } catch (err) {
                console.error("Error triggering pipeline:", err);
                showToast("Erro de Conexão", "Não foi possível conectar à API para executar o pipeline.", "error");
            } finally {
                // Trigger one last fetch to reflect final state
                fetchPipelineStatus();
                // Also refresh the charts and leads since new news might have arrived
                fetchStatsAndRenderCharts();
                fetchLeads();
                fetchGeminiUsage();
            }
        }"""

replacement = """        async function triggerManualPipeline(onlyEditor = false) {
            if (!token) return;
            const triggerBtn = document.getElementById("triggerPipelineBtn");
            const editorBtn = document.getElementById("triggerEditorBtn");
            
            const activeBtn = onlyEditor && editorBtn ? editorBtn : triggerBtn;
            const otherBtn = onlyEditor && editorBtn ? triggerBtn : editorBtn;
            
            // Optimistic UI disable
            if (activeBtn) {
                activeBtn.disabled = true;
                activeBtn.innerHTML = `
                    <svg class="animate-spin h-4 w-4 text-black inline-block" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    <span>Enviando Comando...</span>
                `;
            }
            if (otherBtn) {
                otherBtn.disabled = true;
            }

            // Start polling immediately so the UI catches the status transition to "running"
            startPipelinePolling();

            try {
                const url = onlyEditor ? `${API_BASE_URL}/api/admin/coleta-manual?only_editor=true` : `${API_BASE_URL}/api/admin/coleta-manual`;
                const response = await fetch(url, {
                    method: "POST",
                    headers: {
                        "Authorization": `Bearer ${token}`
                    }
                });

                if (response.ok) {
                    showToast("Pipeline Concluído", onlyEditor ? "O processamento com o Editor Executivo foi concluído com sucesso!" : "A curadoria de notícias e processamento com IA foi concluído com sucesso!", "success");
                } else {
                    const data = await response.json();
                    showToast("Falha no Pipeline", data.detail || "Erro inesperado ao executar o pipeline.", "error");
                }
            } catch (err) {
                console.error("Error triggering pipeline:", err);
                showToast("Erro de Conexão", "Não foi possível conectar à API para executar o pipeline.", "error");
            } finally {
                // Restore button content
                if (triggerBtn) {
                    triggerBtn.disabled = false;
                    triggerBtn.innerHTML = `
                        <i data-lucide="zap" class="w-3.5 h-3.5"></i>
                        <span>Executar</span>
                    `;
                }
                if (editorBtn) {
                    editorBtn.disabled = false;
                    editorBtn.innerHTML = `
                        <i data-lucide="pen-tool" class="w-3.5 h-3.5"></i>
                        <span>Executar Editor</span>
                    `;
                }
                
                // Trigger one last fetch to reflect final state
                fetchPipelineStatus();
                // Also refresh the charts and leads since new news might have arrived
                fetchStatsAndRenderCharts();
                fetchLeads();
                fetchGeminiUsage();
                
                // Re-render Lucide icons
                if (typeof lucide !== 'undefined') {
                    lucide.createIcons();
                }
            }
        }"""

# Normalize line endings to avoid mismatch
normalized_content = content.replace("\r\n", "\n")
normalized_target = target.replace("\r\n", "\n")
normalized_replacement = replacement.replace("\r\n", "\n")

if normalized_target in normalized_content:
    new_content = normalized_content.replace(normalized_target, normalized_replacement)
    # Write back preserving the file's original style CRLF
    with open(file_path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(new_content)
    print("SUCCESS")
else:
    print("TARGET NOT FOUND")
