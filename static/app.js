class SuperBizAgentApp {
    constructor(currentUser = null) {
        this.apiBaseUrl = "/api";
        this.currentMode = "stream";
        this.sessionId = this.generateSessionId();
        this.isStreaming = false;
        this.typewriterDelayMs = 12;
        this.typewriterMediumDelayMs = 8;
        this.typewriterFastDelayMs = 4;
        this.typewriterBacklogDivisor = 18;
        this.typewriterMinChunkSize = 2;
        this.typewriterMaxChunkSize = 24;
        this.typewriterFinishingBacklogDivisor = 8;
        this.typewriterFinishingMinChunkSize = 8;
        this.typewriterFinishingMaxChunkSize = 64;
        this.markdownRenderCache = new Map();
        this.markdownRenderCacheMaxEntries = 48;
        this.messageInputMaxHeight = 200;
        this.shouldAutoScroll = true;
        this.scrollAnimationFrame = 0;
        this.scrollStateAnimationFrame = 0;
        this.pendingScrollToBottom = false;
        this.stopRequested = false;
        this.activeAbortController = null;
        this.activeTypewriter = null;
        this.currentChatHistory = [];
        this.chatHistories = [];
        this.pendingImages = [];
        this.imageUploadMaxCount = 4;
        this.imageUploadMaxSize = 10 * 1024 * 1024;
        this.currentUser = currentUser;
        this.theme = this.loadTheme();
        this.promptTemplates = this.createPromptTemplates();
        this.selectedPromptTemplate = null;
        this.availableModels = [];
        this.currentModel = this.loadPreferredModel();
        this.scriptPromptState = {
            parsedScript: null,
            generationType: "character",
        };

        this.initializeElements();
        this.applyTheme(this.theme);
        this.bindEvents();
        this.closeMobileSidebar();
        this.renderUser();
        this.updateThemeControls();
        this.renderChatHistory();
        this.loadChatHistoriesFromServer();
        this.loadChatModelsFromServer();
        this.updateUI();
        this.renderScriptPromptParsed();
        this.renderScriptPromptTargets();
        this.resizeMessageInput();
        this.checkAndSetCentered();
    }

    initializeElements() {
        this.appLayout = document.getElementById("appLayout") || document.querySelector(".app-layout");
        this.sidebar = document.getElementById("sidebar") || document.querySelector(".sidebar");
        this.mobileMenuBtn = document.getElementById("mobileMenuBtn");
        this.sidebarOverlay = document.getElementById("sidebarOverlay");
        this.newChatBtn = document.getElementById("newChatBtn");
        this.logoutBtn = document.getElementById("logoutBtn");
        this.creationDiagnosisBtn =
            document.getElementById("creationDiagnosisBtn") ||
            document.getElementById("aiOpsSidebarBtn");
        this.userAvatarBtn = document.getElementById("userAvatarBtn");
        this.userAvatarImage = document.getElementById("userAvatarImage");
        this.userAvatarFallback = document.getElementById("userAvatarFallback");
        this.userMenuAvatarImage = document.getElementById("userMenuAvatarImage");
        this.userMenuAvatarFallback = document.getElementById("userMenuAvatarFallback");
        this.userMenu = document.getElementById("userMenu");
        this.userDisplayName = document.getElementById("userDisplayName");
        this.accountEnergyValue = document.getElementById("accountEnergyValue");
        this.userMenuEnergyValue = document.getElementById("userMenuEnergyValue");
        this.themeToggleButton = document.getElementById("themeToggleButton");
        this.quickPrompts = document.getElementById("quickPrompts");
        this.templateHint = document.getElementById("templateHint");
        this.templateHintText = document.getElementById("templateHintText");
        this.clearTemplateBtn = document.getElementById("clearTemplateBtn");
        this.templateSelectorBtn = document.getElementById("templateSelectorBtn");
        this.templateMenu = document.getElementById("templateMenu");
        this.messageInput = document.getElementById("messageInput");
        this.sendButton = document.getElementById("sendButton");
        this.stopButton = document.getElementById("stopButton");
        this.toolsBtn = document.getElementById("toolsBtn");
        this.toolsMenu = document.getElementById("toolsMenu");
        this.uploadFileItem = document.getElementById("uploadFileItem");
        this.uploadImageItem = document.getElementById("uploadImageItem");
        this.fileInput = document.getElementById("fileInput");
        this.imageInput = document.getElementById("imageInput");
        this.modelSelectorBtn = document.getElementById("modelSelectorBtn");
        this.modelDropdown = document.getElementById("modelDropdown");
        this.modelMenuList = document.getElementById("modelMenuList");
        this.currentModelText = document.getElementById("currentModelText");
        this.modeSelectorBtn = document.getElementById("modeSelectorBtn");
        this.modeDropdown = document.getElementById("modeDropdown");
        this.currentModeText = document.getElementById("currentModeText");
        this.chatMessages = document.getElementById("chatMessages");
        this.chatContainer = document.querySelector(".chat-container");
        this.chatInputContainer = document.querySelector(".chat-input-container");
        this.inputWrapper = document.querySelector(".input-wrapper");
        this.chatHistoryList = document.getElementById("chatHistoryList");
        this.loadingOverlay = document.getElementById("loadingOverlay");
        this.scriptPromptBtn = document.getElementById("scriptPromptBtn");
        this.scriptPromptOverlay = document.getElementById("scriptPromptOverlay");
        this.scriptPromptPanel = document.getElementById("scriptPromptPanel");
        this.scriptPromptCloseBtn = document.getElementById("scriptPromptCloseBtn");
        this.scriptPromptTitleInput = document.getElementById("scriptPromptTitleInput");
        this.scriptPromptTextInput = document.getElementById("scriptPromptTextInput");
        this.scriptPromptFileBtn = document.getElementById("scriptPromptFileBtn");
        this.scriptPromptFileInput = document.getElementById("scriptPromptFileInput");
        this.scriptPromptParseBtn = document.getElementById("scriptPromptParseBtn");
        this.scriptPromptStatus = document.getElementById("scriptPromptStatus");
        this.scriptPromptStructure = document.getElementById("scriptPromptStructure");
        this.scriptPromptTypeGrid = document.getElementById("scriptPromptTypeGrid");
        this.scriptPromptTargetSelect = document.getElementById("scriptPromptTargetSelect");
        this.scriptPromptPlatformSelect = document.getElementById("scriptPromptPlatformSelect");
        this.scriptPromptEnglishToggle = document.getElementById("scriptPromptEnglishToggle");
        this.scriptPromptRequirementInput = document.getElementById("scriptPromptRequirementInput");
        this.scriptPromptGenerateBtn = document.getElementById("scriptPromptGenerateBtn");
    }

    bindEvents() {
        this.mobileMenuBtn?.addEventListener("click", (event) => {
            event.stopPropagation();
            this.toggleMobileSidebar();
        });
        this.sidebarOverlay?.addEventListener("click", () => this.closeMobileSidebar());
        this.newChatBtn?.addEventListener("click", () => {
            this.newChat();
            this.closeMobileSidebar();
        });
        this.logoutBtn?.addEventListener("click", () => this.logout());
        this.creationDiagnosisBtn?.addEventListener("click", () => this.triggerCreationDiagnosis());
        this.scriptPromptBtn?.addEventListener("click", () => this.openScriptPromptPanel());
        this.scriptPromptOverlay?.addEventListener("click", () => this.closeScriptPromptPanel());
        this.scriptPromptCloseBtn?.addEventListener("click", () => this.closeScriptPromptPanel());
        this.scriptPromptFileBtn?.addEventListener("click", () => this.scriptPromptFileInput?.click());
        this.scriptPromptFileInput?.addEventListener("change", (event) => this.handleScriptPromptFileSelect(event));
        this.scriptPromptTitleInput?.addEventListener("input", () => this.invalidateScriptPromptParse());
        this.scriptPromptTextInput?.addEventListener("input", () => this.invalidateScriptPromptParse());
        this.scriptPromptParseBtn?.addEventListener("click", () => this.parseScriptPrompt());
        this.scriptPromptGenerateBtn?.addEventListener("click", () => this.generateScriptPrompt());
        this.scriptPromptTypeGrid?.addEventListener("click", (event) => {
            const item = event.target.closest(".script-prompt-type");
            if (!item) return;
            this.selectScriptPromptType(item.dataset.type || "character");
        });
        this.scriptPromptStructure?.addEventListener("click", (event) => {
            const item = event.target.closest("[data-script-target]");
            if (!item) return;
            this.selectScriptPromptTarget(item.dataset.targetType || "character", item.dataset.scriptTarget || "");
        });
        this.userAvatarBtn?.addEventListener("click", (event) => {
            event.stopPropagation();
            this.userAvatarBtn.closest(".user-menu-wrapper")?.classList.toggle("active");
        });
        this.themeToggleButton?.addEventListener("click", () => {
            this.toggleTheme();
        });
        this.quickPrompts?.querySelectorAll(".quick-prompt-card").forEach((card) => {
            card.addEventListener("click", () => {
                if (!this.messageInput || this.isStreaming) return;
                if (card.dataset.template) {
                    this.selectPromptTemplate(card.dataset.template);
                } else {
                    this.messageInput.value = card.dataset.prompt || card.textContent.trim();
                }
                this.resizeMessageInput();
                this.messageInput.focus();
            });
        });
        this.clearTemplateBtn?.addEventListener("click", () => this.clearPromptTemplate());
        this.templateSelectorBtn?.addEventListener("click", (event) => {
            event.stopPropagation();
            this.templateSelectorBtn.closest(".template-selector-wrapper")?.classList.toggle("active");
        });
        this.templateMenu?.querySelectorAll(".template-menu-item").forEach((item) => {
            item.addEventListener("click", () => {
                if (item.dataset.templateClear) {
                    this.clearPromptTemplate();
                } else if (item.dataset.template) {
                    this.selectPromptTemplate(item.dataset.template);
                }
                this.closeTemplateMenu();
                this.messageInput?.focus();
            });
        });
        this.sendButton?.addEventListener("click", () => this.sendMessage());
        this.stopButton?.addEventListener("click", () => this.stopCurrentResponse());
        this.messageInput?.addEventListener("input", () => this.resizeMessageInput());
        this.messageInput?.addEventListener("keydown", (event) => {
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                this.sendMessage();
            }
        });
        window.addEventListener("resize", () => {
            this.resizeMessageInput();
            if (!this.isDrawerLayout()) {
                this.closeMobileSidebar();
            }
        });
        this.chatMessages?.addEventListener("scroll", () => this.handleChatScroll(), { passive: true });

        this.toolsBtn?.addEventListener("click", (event) => {
            event.stopPropagation();
            this.toolsBtn.closest(".tools-btn-wrapper")?.classList.toggle("active");
        });
        this.uploadFileItem?.addEventListener("click", () => {
            this.fileInput?.click();
            this.closeToolsMenu();
        });
        this.uploadImageItem?.addEventListener("click", () => {
            this.imageInput?.click();
            this.closeToolsMenu();
        });
        this.fileInput?.addEventListener("change", (event) => this.handleFileSelect(event));
        this.imageInput?.addEventListener("change", (event) => this.handleImageSelect(event));

        this.modelSelectorBtn?.addEventListener("click", (event) => {
            event.stopPropagation();
            this.modelSelectorBtn.closest(".model-selector-wrapper")?.classList.toggle("active");
        });
        this.modelMenuList?.addEventListener("click", (event) => {
            const item = event.target.closest(".model-menu-item");
            if (!item) return;
            this.selectModel(item.dataset.model || "");
            this.closeModelDropdown();
        });

        this.modeSelectorBtn?.addEventListener("click", (event) => {
            event.stopPropagation();
            this.modeSelectorBtn.closest(".mode-selector-wrapper")?.classList.toggle("active");
        });
        document.querySelectorAll(".dropdown-item").forEach((item) => {
            item.addEventListener("click", () => {
                this.selectMode(item.dataset.mode || "quick");
                this.closeModeDropdown();
            });
        });

        document.addEventListener("click", (event) => {
            if (this.toolsBtn && !this.toolsBtn.contains(event.target) && !this.toolsMenu?.contains(event.target)) {
                this.closeToolsMenu();
            }
            if (
                this.modelSelectorBtn &&
                !this.modelSelectorBtn.contains(event.target) &&
                !this.modelDropdown?.contains(event.target)
            ) {
                this.closeModelDropdown();
            }
            if (
                this.modeSelectorBtn &&
                !this.modeSelectorBtn.contains(event.target) &&
                !this.modeDropdown?.contains(event.target)
            ) {
                this.closeModeDropdown();
            }
            if (
                this.templateSelectorBtn &&
                !this.templateSelectorBtn.contains(event.target) &&
                !this.templateMenu?.contains(event.target)
            ) {
                this.closeTemplateMenu();
            }
            if (
                this.userAvatarBtn &&
                !this.userAvatarBtn.contains(event.target) &&
                !this.userMenu?.contains(event.target)
            ) {
                this.closeUserMenu();
            }
            if (!event.target.closest(".message-actions")) {
                this.closeMobileMessageActions();
            }
        });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                this.closeMobileSidebar();
                this.closeMobileMessageActions();
                this.closeToolsMenu();
                this.closeModeDropdown();
                this.closeTemplateMenu();
                this.closeUserMenu();
                this.closeScriptPromptPanel();
            }
        });
    }

    createPromptTemplates() {
        return {
            character: {
                label: "角色生成",
                placeholder: "输入角色想法，例如：一个古风女杀手，外冷内热，曾是宫廷暗卫…",
                runtimeInstruction: `任务类型：角色生成 / 人物设定 / 角色三视图
原始需求：
{{input}}

请按角色生成模板输出，必须包含人物三视图设定卡要求。保留用户指定画风；未指定画风时默认真人写实风格。`,
            },
            scene: {
                label: "场景提示词",
                placeholder: "输入场景想法，例如：雨夜皇宫内殿，女主发现密信…",
                runtimeInstruction: `任务类型：场景提示词
原始需求：
{{input}}

请按场景画面模板输出，聚焦空间、光影、氛围、构图和影像风格。`,
            },
            expression: {
                label: "表情语气",
                placeholder: "输入角色情绪或台词，例如：她明明生气却强装平静…",
                runtimeInstruction: `任务类型：表情语气模板
原始需求：
{{input}}

请按表情语气模板输出，只聚焦脸部表情、眼神和声音/台词语气。`,
            },
            storyboard: {
                label: "分镜脚本",
                placeholder: "输入剧情段落，例如：女主雨夜闯宫门质问师兄…",
                runtimeInstruction: `任务类型：分镜脚本 / 镜头表格
原始需求：
{{input}}

请按分镜脚本模板输出连续镜头，包含镜号、景别、镜头角度/运动和画面提示词。`,
            },
            action: {
                label: "动作提示词",
                placeholder: "输入动作，例如：角色压抑情绪后突然拔剑…",
                runtimeInstruction: `任务类型：动作拆解 / 动作提示词
原始需求：
{{input}}

请按动作提示词模板输出，聚焦起始姿态、动作过程、力量方向、节奏和镜头建议。`,
            },
            plot: {
                label: "剧情提示词",
                placeholder: "输入剧情想法，例如：主角误以为师兄背叛宗门…",
                runtimeInstruction: `任务类型：剧情策划 / 剧情结构
原始需求：
{{input}}

请按剧情提示词模板输出剧情核心、人物关系、冲突推进、情绪弧线和结尾钩子；不要默认拆分镜。`,
            },
        };
    }

    openScriptPromptPanel() {
        if (!this.scriptPromptPanel || !this.scriptPromptOverlay) return;
        this.scriptPromptPanel.hidden = false;
        this.scriptPromptOverlay.hidden = false;
        document.body.classList.add("script-prompt-open");
        this.scriptPromptTextInput?.focus();
        this.renderScriptPromptTargets();
    }

    closeScriptPromptPanel() {
        if (!this.scriptPromptPanel || !this.scriptPromptOverlay) return;
        this.scriptPromptPanel.hidden = true;
        this.scriptPromptOverlay.hidden = true;
        document.body.classList.remove("script-prompt-open");
    }

    async handleScriptPromptFileSelect(event) {
        const file = event.target.files?.[0];
        if (!file) return;
        if (!/\.(txt|md|markdown)$/i.test(file.name)) {
            this.showNotification("剧本文件仅支持 TXT 或 Markdown", "warning");
            event.target.value = "";
            return;
        }
        if (file.size > 2 * 1024 * 1024) {
            this.showNotification("第一版单个剧本文件请控制在 2MB 以内", "warning");
            event.target.value = "";
            return;
        }
        try {
            const text = await file.text();
            if (this.scriptPromptTextInput) this.scriptPromptTextInput.value = text;
            if (this.scriptPromptTitleInput && !this.scriptPromptTitleInput.value.trim()) {
                this.scriptPromptTitleInput.value = file.name.replace(/\.(txt|md|markdown)$/i, "");
            }
            this.invalidateScriptPromptParse("剧本已读取，请点击解析剧本");
            this.showNotification("剧本已读取", "success");
        } catch (error) {
            this.showNotification("读取剧本文件失败", "error");
        } finally {
            event.target.value = "";
        }
    }

    async parseScriptPrompt() {
        const scriptText = this.scriptPromptTextInput?.value.trim() || "";
        const title = this.scriptPromptTitleInput?.value.trim() || "";
        if (!scriptText) {
            this.showNotification("请先粘贴剧本内容", "warning");
            return;
        }
        this.setScriptPromptBusy(true, "正在解析剧本...");
        try {
            const response = await fetch(`${this.apiBaseUrl}/script-prompts/parse`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "include",
                body: JSON.stringify({
                    scriptText,
                    title,
                }),
            });
            const result = await this.readJsonResponse(response);
            this.scriptPromptState.parsedScript = result.data?.script || null;
            this.renderScriptPromptParsed();
            this.renderScriptPromptTargets();
            this.showNotification("剧本解析完成", "success");
        } catch (error) {
            this.showNotification(error.message || "剧本解析失败", "error");
            if (this.scriptPromptStatus) this.scriptPromptStatus.textContent = "解析失败";
        } finally {
            this.setScriptPromptBusy(false);
        }
    }

    setScriptPromptBusy(isBusy, statusText = "") {
        if (this.scriptPromptParseBtn) this.scriptPromptParseBtn.disabled = isBusy;
        if (this.scriptPromptGenerateBtn) {
            this.scriptPromptGenerateBtn.disabled = isBusy || !this.scriptPromptState.parsedScript;
        }
        if (this.scriptPromptStatus && statusText) this.scriptPromptStatus.textContent = statusText;
    }

    invalidateScriptPromptParse(statusText = "剧本内容已修改，请重新解析") {
        if (!this.scriptPromptState.parsedScript) return;
        this.scriptPromptState.parsedScript = null;
        this.renderScriptPromptParsed(statusText);
        this.renderScriptPromptTargets();
    }

    renderScriptPromptParsed(emptyStatusText = "尚未解析剧本") {
        const script = this.scriptPromptState.parsedScript;
        if (!this.scriptPromptStructure || !this.scriptPromptStatus) return;
        if (!script) {
            this.scriptPromptStatus.textContent = emptyStatusText;
            this.scriptPromptStructure.innerHTML = `
                <div class="script-prompt-empty-state">
                    <strong>解析后在这里查看人物和场景</strong>
                    <span>左侧粘贴或上传剧本，点击“解析剧本”后，可直接点选人物或场景联动右侧生成设置。</span>
                </div>
            `;
            return;
        }

        const stats = script.stats || {};
        this.scriptPromptStatus.textContent =
            `《${script.title || "未命名剧本"}》已识别 ${stats.character_count || 0} 个角色、` +
            `${stats.scene_count || 0} 个场景、${stats.chunk_count || 0} 个引用片段`;

        const characters = (script.characters || []).map((character) => `
            <button type="button" class="script-prompt-chip" data-target-type="character" data-script-target="${this.escapeHtml(character.name)}">
                <span>${this.escapeHtml(character.name)}</span>
            </button>
        `).join("");
        const scenes = (script.scenes || []).map((scene) => `
            <button type="button" class="script-prompt-structure-item" data-target-type="scene" data-script-target="${this.escapeHtml(scene.scene_number || scene.location || "")}">
                <span>${this.escapeHtml(scene.scene_number || "场景")}</span>
                <small>${this.escapeHtml([scene.location, scene.time].filter(Boolean).join(" / "))}</small>
            </button>
        `).join("");

        this.scriptPromptStructure.innerHTML = `
            <div class="script-prompt-stats">
                <span>角色 ${stats.character_count || 0}</span>
                <span>场景 ${stats.scene_count || 0}</span>
                <span>片段 ${stats.chunk_count || 0}</span>
            </div>
            <div class="script-prompt-structure-section">
                <h3>人物</h3>
                <div class="script-prompt-chip-row">${characters || "<span class='script-prompt-muted'>未识别到人物表</span>"}</div>
            </div>
            <div class="script-prompt-structure-section">
                <h3>场景</h3>
                <div class="script-prompt-scene-list">${scenes || "<span class='script-prompt-muted'>未识别到场景标题</span>"}</div>
            </div>
        `;
    }

    selectScriptPromptType(type) {
        const allowedTypes = ["character", "scene", "storyboard", "action", "plot"];
        this.scriptPromptState.generationType = allowedTypes.includes(type) ? type : "character";
        this.scriptPromptTypeGrid?.querySelectorAll(".script-prompt-type").forEach((item) => {
            item.classList.toggle("active", item.dataset.type === this.scriptPromptState.generationType);
        });
        this.renderScriptPromptTargets();
    }

    selectScriptPromptTarget(type, target) {
        if (type === "character") {
            this.selectScriptPromptType("character");
        } else if (type === "scene" && !["scene", "storyboard", "action"].includes(this.scriptPromptState.generationType)) {
            this.selectScriptPromptType("scene");
        }
        this.renderScriptPromptTargets(target);
        const typeLabel = this.getScriptPromptTypeLabel(this.scriptPromptState.generationType);
        if (this.scriptPromptRequirementInput && !this.scriptPromptRequirementInput.value.trim()) {
            this.scriptPromptRequirementInput.value = `生成${target}的${typeLabel}，真人写实电影感，适合 AI 短剧。`;
        }
        this.scriptPromptRequirementInput?.focus();
    }

    renderScriptPromptTargets(preferredTarget = "") {
        if (!this.scriptPromptTargetSelect) return;
        const script = this.scriptPromptState.parsedScript;
        const type = this.scriptPromptState.generationType;
        const options = this.getScriptPromptTargetOptions(script, type);
        const current = preferredTarget || this.scriptPromptTargetSelect.value;
        this.scriptPromptTargetSelect.innerHTML = options.map((option) => `
            <option value="${this.escapeHtml(option.value)}">${this.escapeHtml(option.label)}</option>
        `).join("");
        const matched = options.find((option) => option.value === current);
        this.scriptPromptTargetSelect.value = matched?.value || options[0]?.value || "";
        if (this.scriptPromptGenerateBtn) {
            this.scriptPromptGenerateBtn.disabled = !script || !this.scriptPromptTargetSelect.value;
        }
    }

    getScriptPromptTargetOptions(script, type) {
        if (!script) {
            return [{ value: "", label: "请先解析剧本" }];
        }
        if (type === "character") {
            const characters = script.characters || [];
            return characters.length
                ? characters.map((character) => ({ value: character.name, label: character.name }))
                : [{ value: "", label: "未识别到角色" }];
        }
        if (["scene", "storyboard", "action"].includes(type)) {
            const scenes = script.scenes || [];
            return scenes.length
                ? scenes.map((scene) => ({
                    value: scene.scene_number || scene.location,
                    label: [scene.scene_number, scene.location, scene.time].filter(Boolean).join(" / "),
                }))
                : [{ value: "", label: "未识别到场景" }];
        }
        if (type === "plot") {
            return [{ value: script.title || "整部剧", label: `整部剧：${script.title || "当前剧本"}` }];
        }
        return [{ value: script.title || "当前剧本", label: script.title || "当前剧本" }];
    }

    async generateScriptPrompt() {
        if (this.isStreaming) {
            this.showNotification("请等待当前回答完成", "warning");
            return;
        }
        const parsedScript = this.scriptPromptState.parsedScript;
        if (!parsedScript) {
            this.showNotification("请先解析剧本", "warning");
            return;
        }
        const target = this.scriptPromptTargetSelect?.value || "";
        const userRequirement = this.scriptPromptRequirementInput?.value.trim() || "";
        const generationType = this.scriptPromptState.generationType;
        const promptTemplate = this.getScriptPromptTemplateForType(generationType);
        if (!promptTemplate) {
            this.showNotification("当前类型没有对应的系统提示词模板", "warning");
            return;
        }
        this.setScriptPromptBusy(true, "正在整理剧本引用...");
        try {
            const response = await fetch(`${this.apiBaseUrl}/script-prompts/references`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "include",
                body: JSON.stringify({
                    parsedScript,
                    generationType,
                    target,
                    platform: this.scriptPromptPlatformSelect?.value || "general",
                    userRequirement,
                    includeEnglish: Boolean(this.scriptPromptEnglishToggle?.checked),
                }),
            });
            const result = await this.readJsonResponse(response);
            const referenceData = result.data || null;
            const displayQuestion = this.buildScriptPromptDisplayQuestion(referenceData, userRequirement);
            const modelQuestion = this.buildScriptPromptModelQuestion(referenceData, userRequirement);
            this.closeScriptPromptPanel();
            await this.startScriptPromptChat(displayQuestion, promptTemplate, modelQuestion);
            this.showNotification("已在对话区生成提示词", "success");
        } catch (error) {
            this.showNotification(error.message || "剧本提示词生成失败", "error");
        } finally {
            this.setScriptPromptBusy(false, parsedScript ? `《${parsedScript.title || "当前剧本"}》已解析` : "");
        }
    }

    getScriptPromptTypeLabel(type) {
        const labels = {
            character: "人物提示词",
            scene: "场景提示词",
            storyboard: "分镜提示词",
            action: "动作提示词",
            plot: "剧情提示词",
        };
        return labels[type] || "提示词";
    }

    getScriptPromptTemplateForType(type) {
        const mapping = {
            character: "character",
            scene: "scene",
            storyboard: "storyboard",
            action: "action",
            plot: "plot",
        };
        return mapping[type] || "";
    }

    buildScriptPromptDisplayQuestion(data, userRequirement = "") {
        const scriptTitle = data?.script?.title || this.scriptPromptState.parsedScript?.title || "当前剧本";
        const generationType = data?.generationType || this.scriptPromptState.generationType;
        const target = data?.target || this.scriptPromptTargetSelect?.value || scriptTitle;
        const platform = this.getScriptPromptPlatformLabel(data?.platform || this.scriptPromptPlatformSelect?.value || "general");
        const typeLabel = this.getScriptPromptTypeLabel(generationType);
        const includeEnglish = Boolean(data?.includeEnglish || this.scriptPromptEnglishToggle?.checked);
        const lines = [
            `基于剧本《${scriptTitle}》，生成${target ? `「${target}」的` : ""}${typeLabel}。`,
            `平台用途：${platform}`,
        ];
        if (userRequirement) lines.push(`补充需求：${userRequirement}`);
        if (includeEnglish) lines.push("同时生成英文版。");
        return lines.join("\n");
    }

    buildScriptPromptModelQuestion(data, userRequirement = "") {
        const scriptTitle = data?.script?.title || this.scriptPromptState.parsedScript?.title || "当前剧本";
        const generationType = data?.generationType || this.scriptPromptState.generationType;
        const target = data?.target || this.scriptPromptTargetSelect?.value || scriptTitle;
        const platform = this.getScriptPromptPlatformLabel(data?.platform || this.scriptPromptPlatformSelect?.value || "general");
        const typeLabel = this.getScriptPromptTypeLabel(generationType);
        const templateLabel = this.promptTemplates[this.getScriptPromptTemplateForType(generationType)]?.label || typeLabel;
        const includeEnglish = Boolean(data?.includeEnglish || this.scriptPromptEnglishToggle?.checked);
        const references = data?.references || [];
        const referenceText = references.map((reference, index) => [
            `引用 ${index + 1}`,
            `chunk_id：${reference.chunk_id || ""}`,
            `来源：${reference.source || ""}`,
            `原文：${reference.quote || ""}`,
            `用途：${reference.usage || ""}`,
        ].join("\n")).join("\n\n");

        return [
            "【剧本引用提示词生成任务】",
            `请基于剧本《${scriptTitle}》生成${target ? `「${target}」的` : ""}${typeLabel}。`,
            `请按当前选择的「${templateLabel}」创作模板输出，不要另起自由格式。`,
            `平台用途：${platform}`,
            `英文版：${includeEnglish ? "需要生成" : "不需要，除非我后续明确要求"}`,
            `补充需求：${userRequirement || "保持剧本设定，适合 AI 漫剧 / AI 短剧生产。"}`,
            "输出要求：",
            ...(generationType === "character" ? [
                "0. 这是人物/角色提示词任务，必须输出人物三视图设定卡，包含正视图、侧视图、后视图的一致性要求。",
            ] : []),
            "1. 负面提示词必须保留。",
            "2. 引用依据只能使用下面的剧本片段，不要编造剧本原文。",
            "3. 剧本没有直接写明但为了视觉化需要补充的内容，必须标为合理推断。",
            "4. 最终提示词要方便直接使用。",
            "【剧本引用片段】",
            referenceText || "暂无可用引用片段。",
        ].join("\n");
    }

    getScriptPromptPlatformLabel(value) {
        const labels = {
            general: "通用",
            midjourney: "Midjourney",
            stable_diffusion: "Stable Diffusion",
            jimeng: "即梦",
            kling: "可灵",
            runway: "Runway",
            pika: "Pika",
        };
        return labels[value] || value || "通用";
    }

    async startScriptPromptChat(displayQuestion, promptTemplate, modelQuestion = displayQuestion) {
        if (!["quick", "stream"].includes(this.currentMode)) {
            this.selectMode("stream");
        }
        const selectedModel = this.getCurrentModel();
        const userMessage = this.addMessage("user", displayQuestion, true, false, {
            model: selectedModel,
            promptTemplate,
        });
        if (this.messageInput) this.messageInput.value = "";
        this.resizeMessageInput();
        this.isStreaming = true;
        this.stopRequested = false;
        this.updateUI();

        const assistantMetadata = {
            id: this.generateMessageId(),
            prompt: displayQuestion,
            modelPrompt: modelQuestion,
            model: selectedModel,
            promptTemplate,
            userMessageId: userMessage.dataset.messageId,
        };
        const assistantMessage = this.addMessage(
            "assistant",
            "火宝正在按照剧本引用和系统模板生成...",
            false,
            true,
            assistantMetadata
        );

        try {
            if (this.currentMode === "quick") {
                await this.sendQuickMessage(displayQuestion, assistantMessage, assistantMetadata);
            } else {
                await this.sendStreamMessage(displayQuestion, assistantMessage, assistantMetadata);
            }
        } catch (error) {
            if (this.stopRequested || error.name === "AbortError") {
                this.updateMessage(assistantMessage, "已停止生成");
            } else {
                this.updateMessage(assistantMessage, `抱歉，处理时出现错误：${error.message}`);
                throw error;
            }
        } finally {
            this.activeAbortController = null;
            this.activeTypewriter = null;
            this.isStreaming = false;
            this.stopRequested = false;
            this.updateUI();
            this.saveCurrentChat();
        }
    }

    selectPromptTemplate(templateKey) {
        if (!this.promptTemplates[templateKey]) return;
        this.selectedPromptTemplate = templateKey;
        if (!["quick", "stream"].includes(this.currentMode)) {
            this.selectMode("stream");
        }
        this.updatePromptTemplateUI();
        this.updateUI();
        this.showNotification(`已启用${this.promptTemplates[templateKey].label}模板`, "success");
    }

    clearPromptTemplate() {
        this.selectedPromptTemplate = null;
        this.updatePromptTemplateUI();
        this.updateUI();
        this.messageInput?.focus();
    }

    getActivePromptTemplate() {
        if (!["quick", "stream"].includes(this.currentMode)) return null;
        return this.promptTemplates[this.selectedPromptTemplate] || null;
    }

    buildModelQuestion(question) {
        const template = this.getActivePromptTemplate();
        if (!template) return question;
        return template.runtimeInstruction.replace("{{input}}", question.trim());
    }

    loadPreferredModel() {
        return localStorage.getItem("juchengCurrentModel") || "";
    }

    async loadChatModelsFromServer() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/chat/model-options`, {
                credentials: "include",
            });
            const result = await this.readJsonResponse(response);
            this.availableModels = result.data?.models || [];
            const defaultModel = result.data?.defaultModel;
            const savedModel = this.currentModel;
            const hasSavedModel = this.availableModels.some((model) => model.modelId === savedModel);
            this.currentModel = hasSavedModel
                ? savedModel
                : defaultModel?.modelId || this.availableModels[0]?.modelId || savedModel || "";
            if (this.currentModel) {
                localStorage.setItem("juchengCurrentModel", this.currentModel);
            }
            this.renderModelMenu();
            this.updateModelUI();
        } catch (error) {
            console.warn("加载模型列表失败:", error);
            if (!this.currentModel) this.currentModel = "qwen3.7-plus";
            this.availableModels = [{
                modelId: this.currentModel,
                displayName: this.currentModel,
                isDefault: true,
            }];
            this.renderModelMenu();
            this.updateModelUI();
        }
    }

    selectModel(modelId) {
        if (!modelId || this.isStreaming) return;
        const exists = this.availableModels.some((model) => model.modelId === modelId);
        if (!exists) return;
        this.currentModel = modelId;
        localStorage.setItem("juchengCurrentModel", this.currentModel);
        this.updateModelUI();
    }

    getCurrentModel() {
        return this.currentModel || this.availableModels[0]?.modelId || "";
    }

    getModelById(modelId) {
        return this.availableModels.find((model) => model.modelId === modelId) || null;
    }

    renderModelMenu() {
        if (!this.modelMenuList) return;
        if (!this.availableModels.length) {
            this.modelMenuList.innerHTML = `<div class="dropdown-item-sub">暂无可用模型</div>`;
            return;
        }
        this.modelMenuList.innerHTML = this.availableModels.map((model) => `
            <div class="model-menu-item" data-model="${this.escapeHtml(model.modelId)}">
                <div class="dropdown-item-main">
                    <span>${this.escapeHtml(model.displayName || model.modelId)}</span>
                    ${model.isDefault ? `<span class="badge-new">默认</span>` : ""}
                </div>
                <div class="dropdown-item-sub">${this.escapeHtml(model.modelId)}</div>
            </div>
        `).join("");
        this.updateModelUI();
    }

    updateModelUI() {
        const modelId = this.getCurrentModel();
        const model = this.getModelById(modelId);
        if (this.currentModelText) {
            this.currentModelText.textContent = model?.displayName || modelId || "模型";
        }
        this.modelMenuList?.querySelectorAll(".model-menu-item").forEach((item) => {
            item.classList.toggle("active", item.dataset.model === modelId);
        });
    }

    updatePromptTemplateUI() {
        const template = this.getActivePromptTemplate();
        this.quickPrompts?.querySelectorAll(".quick-prompt-card").forEach((card) => {
            card.classList.toggle("active", Boolean(template && card.dataset.template === this.selectedPromptTemplate));
        });
        if (this.templateHint) {
            this.templateHint.hidden = !template;
        }
        if (this.templateHintText) {
            this.templateHintText.textContent = template ? `当前模板：${template.label}` : "";
        }
        if (this.templateSelectorBtn) {
            this.templateSelectorBtn.classList.toggle("active", Boolean(template));
            this.templateSelectorBtn.querySelector("span").textContent = template ? template.label : "模板";
        }
        this.templateMenu?.querySelectorAll(".template-menu-item[data-template]").forEach((item) => {
            item.classList.toggle("active", Boolean(template && item.dataset.template === this.selectedPromptTemplate));
        });
    }

    renderUser() {
        const phone = this.currentUser?.phone;
        const displayName = this.getAccountDisplayName();
        const fallbackText = phone ? phone.slice(-2) : "创";
        const avatarUrl = this.getUserAvatarUrl();

        if (this.userDisplayName) {
            this.userDisplayName.textContent = displayName;
        }
        if (this.accountEnergyValue) {
            this.accountEnergyValue.textContent = this.formatEnergyValue(this.getAccountEnergy());
        }
        if (this.userMenuEnergyValue) {
            this.userMenuEnergyValue.textContent = this.formatEnergyValue(this.getAccountEnergy());
        }
        this.renderAvatarSlot(this.userAvatarImage, this.userAvatarFallback, avatarUrl, fallbackText);
        this.renderAvatarSlot(this.userMenuAvatarImage, this.userMenuAvatarFallback, avatarUrl, fallbackText);
        this.updateAIOpsVisibility();
    }

    hasAIOpsAccess() {
        return this.currentUser?.role === "super_admin";
    }

    updateAIOpsVisibility() {
        if (!this.creationDiagnosisBtn) return;
        const canUseAIOps = this.hasAIOpsAccess();
        this.creationDiagnosisBtn.hidden = !canUseAIOps;
        this.creationDiagnosisBtn.setAttribute("aria-hidden", canUseAIOps ? "false" : "true");
    }

    getAccountDisplayName() {
        const nickname = this.currentUser?.nickname?.trim();
        const phone = this.currentUser?.phone || this.currentUser?.mobile || "";
        if (nickname) return nickname;
        return phone ? this.maskPhone(phone) : "创作者";
    }

    maskPhone(phone) {
        if (!phone || phone.length < 7) return phone || "";
        return `${phone.slice(0, 3)}****${phone.slice(-4)}`;
    }

    getAccountEnergy() {
        const energy =
            this.currentUser?.ai_energy ??
            this.currentUser?.aiEnergy ??
            this.currentUser?.energy ??
            this.currentUser?.points ??
            0;
        const numericEnergy = Number(energy);
        return Number.isFinite(numericEnergy) ? numericEnergy : 0;
    }

    formatEnergyValue(value) {
        const numericValue = Number(value || 0);
        return Number.isFinite(numericValue) ? String(Math.max(0, Math.trunc(numericValue))) : "0";
    }

    getUserAvatarUrl() {
        return (
            this.currentUser?.avatar_url ||
            this.currentUser?.avatarUrl ||
            this.currentUser?.avatar ||
            localStorage.getItem("userAvatarUrl") ||
            ""
        );
    }

    renderAvatarSlot(imageElement, fallbackElement, avatarUrl, fallbackText) {
        if (fallbackElement) fallbackElement.textContent = fallbackText;
        if (!imageElement || !fallbackElement) return;

        if (avatarUrl) {
            imageElement.src = avatarUrl;
            imageElement.hidden = false;
            fallbackElement.hidden = true;
        } else {
            imageElement.removeAttribute("src");
            imageElement.hidden = true;
            fallbackElement.hidden = false;
        }
    }

    selectMode(mode) {
        const allowedModes = ["quick", "stream", "vision", "image"];
        this.currentMode = allowedModes.includes(mode) ? mode : "quick";
        document.querySelectorAll(".dropdown-item").forEach((item) => {
            item.classList.toggle("active", item.dataset.mode === this.currentMode);
        });
        this.updateUI();
        this.resizeMessageInput();
    }

    updateUI() {
        if (this.currentModeText) {
            const modeLabels = {
                quick: "快速",
                stream: "流式",
                vision: "看图",
                image: "生图",
            };
            this.currentModeText.textContent = modeLabels[this.currentMode] || "快速";
        }
        if (this.messageInput) {
            const activeTemplate = this.getActivePromptTemplate();
            const placeholders = {
                quick: "询问知识库、角色设定、剧本流程或创作资产…",
                stream: "询问知识库、角色设定、剧本流程或创作资产…",
                vision: "上传图片后，描述你想让火宝分析的角色、场景或分镜…",
                image: "描述你想生成的角色、场景、分镜或海报…",
            };
            this.messageInput.placeholder = activeTemplate?.placeholder || placeholders[this.currentMode] || placeholders.stream;
        }
        if (this.sendButton) {
            this.sendButton.hidden = this.isStreaming;
            this.sendButton.disabled = this.isStreaming;
        }
        if (this.stopButton) {
            this.stopButton.hidden = !this.isStreaming;
            this.stopButton.disabled = this.stopRequested;
        }
        if (this.messageInput) {
            this.messageInput.disabled = this.isStreaming;
        }
        this.updateModelUI();
        this.updatePromptTemplateUI();
        this.updateAllAssistantActions();
    }

    closeToolsMenu() {
        this.toolsBtn?.closest(".tools-btn-wrapper")?.classList.remove("active");
    }

    closeModeDropdown() {
        this.modeSelectorBtn?.closest(".mode-selector-wrapper")?.classList.remove("active");
    }

    closeModelDropdown() {
        this.modelSelectorBtn?.closest(".model-selector-wrapper")?.classList.remove("active");
    }

    closeTemplateMenu() {
        this.templateSelectorBtn?.closest(".template-selector-wrapper")?.classList.remove("active");
    }

    closeUserMenu() {
        this.userAvatarBtn?.closest(".user-menu-wrapper")?.classList.remove("active");
    }

    isDrawerLayout() {
        return window.matchMedia("(max-width: 1023px)").matches;
    }

    toggleMobileSidebar() {
        if (!this.isDrawerLayout()) return;
        const isOpen = this.appLayout?.classList.contains("sidebar-open");
        if (isOpen) {
            this.closeMobileSidebar();
        } else {
            this.openMobileSidebar();
        }
    }

    openMobileSidebar() {
        if (!this.appLayout || !this.isDrawerLayout()) return;
        this.appLayout.classList.add("sidebar-open");
        document.body.classList.add("is-sidebar-open");
        this.mobileMenuBtn?.setAttribute("aria-expanded", "true");
        this.mobileMenuBtn?.setAttribute("aria-label", "关闭会话列表");
        this.sidebarOverlay?.setAttribute("aria-hidden", "false");
        this.sidebar?.setAttribute("aria-hidden", "false");
    }

    closeMobileSidebar() {
        this.appLayout?.classList.remove("sidebar-open");
        document.body.classList.remove("is-sidebar-open");
        this.mobileMenuBtn?.setAttribute("aria-expanded", "false");
        this.mobileMenuBtn?.setAttribute("aria-label", "打开会话列表");
        this.sidebarOverlay?.setAttribute("aria-hidden", "true");
        if (this.isDrawerLayout()) {
            this.sidebar?.setAttribute("aria-hidden", "true");
        } else {
            this.sidebar?.removeAttribute("aria-hidden");
        }
    }

    closeMobileMessageActions(exceptActions = null) {
        this.chatMessages?.querySelectorAll(".message-actions.mobile-actions-open").forEach((actions) => {
            if (actions !== exceptActions) {
                actions.classList.remove("mobile-actions-open");
            }
        });
    }

    loadTheme() {
        const savedTheme = localStorage.getItem("juchengTheme");
        return savedTheme === "night" ? "night" : "day";
    }

    toggleTheme() {
        this.setTheme(this.theme === "night" ? "day" : "night");
    }

    setTheme(theme) {
        this.theme = theme === "night" ? "night" : "day";
        localStorage.setItem("juchengTheme", this.theme);
        this.applyTheme(this.theme);
        this.updateThemeControls();
    }

    applyTheme(theme) {
        document.documentElement.dataset.theme = theme === "night" ? "night" : "day";
    }

    updateThemeControls() {
        if (!this.themeToggleButton) return;
        const isNight = this.theme === "night";
        this.themeToggleButton.classList.toggle("is-night", isNight);
        this.themeToggleButton.setAttribute("aria-label", isNight ? "切换为白天模式" : "切换为黑夜模式");
        this.themeToggleButton.title = isNight ? "切换为白天模式" : "切换为黑夜模式";
    }

    resizeMessageInput() {
        if (!this.messageInput) return;

        this.messageInputMaxHeight = this.getMessageInputMaxHeight();
        this.messageInput.style.height = "auto";
        const nextHeight = Math.min(this.messageInput.scrollHeight, this.messageInputMaxHeight);
        this.messageInput.style.height = `${nextHeight}px`;
        this.messageInput.style.overflowY =
            this.messageInput.scrollHeight > this.messageInputMaxHeight ? "auto" : "hidden";
        this.updateChatInputSpace();
    }

    getMessageInputMaxHeight() {
        if (window.matchMedia("(max-width: 767px)").matches) return 148;
        if (window.matchMedia("(max-width: 1023px)").matches) return 176;
        return 200;
    }

    updateChatInputSpace() {
        if (!this.chatContainer || !this.chatInputContainer) return;
        const floatingInputHeight = this.chatInputContainer.offsetHeight || 0;
        const bottomGap = window.matchMedia("(max-width: 767px)").matches ? 12 : 18;
        this.chatContainer.style.setProperty("--chat-input-space", `${floatingInputHeight + bottomGap}px`);
    }

    stopCurrentResponse() {
        if (!this.isStreaming || this.stopRequested) return;

        this.stopRequested = true;
        this.activeTypewriter?.stop();
        this.activeAbortController?.abort();
        this.updateUI();
    }

    isNearBottom(threshold = 72) {
        if (!this.chatMessages) return true;
        const distanceFromBottom =
            this.chatMessages.scrollHeight - this.chatMessages.scrollTop - this.chatMessages.clientHeight;
        return distanceFromBottom <= threshold;
    }

    handleChatScroll() {
        if (this.scrollStateAnimationFrame) return;
        this.scrollStateAnimationFrame = window.requestAnimationFrame(() => {
            this.scrollStateAnimationFrame = 0;
            this.shouldAutoScroll = this.isNearBottom();
        });
    }

    newChat() {
        if (this.isStreaming) {
            this.showNotification("请等待当前回答完成", "warning");
            return;
        }
        this.sessionId = this.generateSessionId();
        this.currentChatHistory = [];
        this.clearPendingImages();
        this.shouldAutoScroll = true;
        if (this.chatMessages) {
            this.chatMessages.innerHTML = "";
        }
        if (this.messageInput) {
            this.messageInput.value = "";
            this.resizeMessageInput();
            this.messageInput.focus();
        }
        this.checkAndSetCentered();
        this.renderChatHistory();
    }

    async sendMessage() {
        if (this.isStreaming) return;
        let question = this.messageInput?.value.trim() || "";
        const isImageGenerationRequest = this.currentMode === "image";
        const isVisionRequest =
            !isImageGenerationRequest && (this.currentMode === "vision" || this.pendingImages.length > 0);

        if (isVisionRequest && !this.pendingImages.length) {
            this.showNotification("请先上传需要分析的图片", "warning");
            return;
        }
        if (isVisionRequest && !question) {
            question = "请分析这些图片，并整理成适合 AI 视频提示词创作的人物、场景、影像风格、镜头和分镜要点。";
        }
        if (!question) {
            const activeTemplate = this.getActivePromptTemplate();
            if (activeTemplate) {
                this.showNotification(`请输入要处理的${activeTemplate.label}内容`, "warning");
            }
            return;
        }
        if (isImageGenerationRequest && this.pendingImages.length) {
            this.showNotification("生图模式暂不使用上传图，已按文字提示生成", "info");
        }
        const activeTemplate = !isImageGenerationRequest && !isVisionRequest
            ? this.getActivePromptTemplate()
            : null;
        const modelQuestion = activeTemplate ? this.buildModelQuestion(question) : question;
        const selectedModel = !isImageGenerationRequest && !isVisionRequest ? this.getCurrentModel() : "";

        const imagePayloads = isVisionRequest ? [...this.pendingImages] : [];
        const userImages = imagePayloads.map((image) => ({
            id: image.id,
            name: image.file.name,
            previewUrl: image.previewUrl,
            mimeType: image.file.type,
            fileSize: image.file.size,
        }));
        const userMessage = this.addMessage("user", question, true, false, {
            images: userImages,
            model: selectedModel,
        });
        this.clearPendingImages(!isVisionRequest);
        this.messageInput.value = "";
        this.resizeMessageInput();
        this.isStreaming = true;
        this.stopRequested = false;
        this.updateUI();

        const assistantMetadata = {
            id: this.generateMessageId(),
            prompt: question,
            modelPrompt: modelQuestion,
            model: selectedModel,
            promptTemplate: activeTemplate ? this.selectedPromptTemplate : null,
            userMessageId: userMessage.dataset.messageId,
        };
        const loadingText = isImageGenerationRequest
            ? "火宝正在生成图片..."
            : isVisionRequest
                ? "火宝正在识别图片..."
                : "火宝正在整理知识库内容...";
        const assistantMessage = this.addMessage(
            "assistant",
            loadingText,
            false,
            true,
            assistantMetadata
        );
        try {
            if (isImageGenerationRequest) {
                await this.sendImageGenerationMessage(question, assistantMessage, assistantMetadata);
            } else if (isVisionRequest) {
                await this.sendVisionMessage(question, imagePayloads, assistantMessage, assistantMetadata);
            } else if (this.currentMode === "stream") {
                await this.sendStreamMessage(question, assistantMessage, assistantMetadata);
            } else {
                await this.sendQuickMessage(question, assistantMessage, assistantMetadata);
            }
        } catch (error) {
            if (this.stopRequested || error.name === "AbortError") {
                this.updateMessage(assistantMessage, "已停止生成");
            } else {
                this.updateMessage(assistantMessage, `抱歉，处理时出现错误：${error.message}`);
                this.showNotification(error.message || "请求失败", "error");
            }
        } finally {
            this.activeAbortController = null;
            this.activeTypewriter = null;
            this.isStreaming = false;
            this.stopRequested = false;
            this.updateUI();
            this.saveCurrentChat();
        }
    }

    async sendQuickMessage(question, messageElement, metadata = {}) {
        this.activeAbortController = new AbortController();
        const response = await fetch(`${this.apiBaseUrl}/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({
                Id: this.sessionId,
                Question: question,
                ModelQuestion: metadata.modelPrompt || question,
                Model: metadata.model || this.getCurrentModel(),
                PromptTemplate: metadata.promptTemplate,
                ClientMessageId: metadata.userMessageId,
                AssistantMessageId: metadata.id,
                IsRetry: Boolean(metadata.retryOf),
                RetryOf: metadata.retryOf,
            }),
            signal: this.activeAbortController.signal,
        });
        const result = await this.readJsonResponse(response);
        const answer = result.data?.answer || result.answer || "未获取到回答";
        this.updateMessage(messageElement, answer);
        this.recordAssistantHistory(messageElement, answer, { ...metadata, prompt: question });
    }

    async sendStreamMessage(question, messageElement, metadata = {}) {
        const typewriter = this.createTypewriter(messageElement);
        this.activeTypewriter = typewriter;
        this.activeAbortController = new AbortController();
        let fullAnswer = "";
        let streamCompleted = false;

        try {
            const response = await fetch(`${this.apiBaseUrl}/chat_stream`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "include",
                body: JSON.stringify({
                    Id: this.sessionId,
                    Question: question,
                    ModelQuestion: metadata.modelPrompt || question,
                    Model: metadata.model || this.getCurrentModel(),
                    PromptTemplate: metadata.promptTemplate,
                    ClientMessageId: metadata.userMessageId,
                    AssistantMessageId: metadata.id,
                    IsRetry: Boolean(metadata.retryOf),
                    RetryOf: metadata.retryOf,
                }),
                signal: this.activeAbortController.signal,
            });
            if (!response.ok || !response.body) {
                await this.readJsonResponse(response);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const events = buffer.split(/\r?\n\r?\n/);
                buffer = events.pop() || "";

                for (const event of events) {
                    const dataLine = event.split(/\r?\n/).find((line) => line.startsWith("data:"));
                    if (!dataLine) continue;
                    const payload = dataLine.replace(/^data:\s*/, "");
                    try {
                        const parsed = JSON.parse(payload);
                        if (parsed.type === "content") {
                            fullAnswer += parsed.data || "";
                            typewriter.push(parsed.data || "");
                        } else if (parsed.type === "status") {
                            if (!fullAnswer) {
                                this.updateMessage(messageElement, parsed.data || "火宝正在思考...", true);
                            }
                        } else if (parsed.type === "done") {
                            const finalAnswer = parsed.data?.answer || fullAnswer;
                            fullAnswer = finalAnswer;
                            if (!streamCompleted) {
                                streamCompleted = true;
                                await typewriter.finish(finalAnswer);
                            }
                        } else if (parsed.type === "error") {
                            throw new Error(parsed.data || "流式回答失败");
                        }
                    } catch (error) {
                        if (error instanceof SyntaxError) continue;
                        throw error;
                    }
                }
            }

            const answer = fullAnswer || "回答完成";
            if (!streamCompleted) {
                await typewriter.finish(answer);
            }
            this.recordAssistantHistory(messageElement, answer, { ...metadata, prompt: question });
        } catch (error) {
            if (this.stopRequested || error.name === "AbortError") {
                const partialAnswer = typewriter.stop();
                this.updateMessage(messageElement, partialAnswer || "已停止生成");
                if (partialAnswer) {
                    this.recordAssistantHistory(messageElement, partialAnswer, { ...metadata, prompt: question });
                    await this.persistAssistantMessage(partialAnswer, metadata, { stopped: true });
                }
                return;
            }
            throw error;
        }
    }

    async sendVisionMessage(question, images, messageElement, metadata = {}) {
        this.activeAbortController = new AbortController();
        const formData = new FormData();
        formData.append("session_id", this.sessionId);
        formData.append("question", question);
        formData.append("client_message_id", metadata.userMessageId || "");
        formData.append("assistant_message_id", metadata.id || "");
        images.forEach((image) => formData.append("files", image.file));

        const response = await fetch(`${this.apiBaseUrl}/chat_vision`, {
            method: "POST",
            credentials: "include",
            body: formData,
            signal: this.activeAbortController.signal,
        });
        const result = await this.readJsonResponse(response);
        const answer = result.data?.answer || "图片分析完成";
        this.updateMessage(messageElement, answer);
        this.recordAssistantHistory(messageElement, answer, {
            ...metadata,
            prompt: question,
        });
    }

    async sendImageGenerationMessage(prompt, messageElement, metadata = {}) {
        this.activeAbortController = new AbortController();
        const response = await fetch(`${this.apiBaseUrl}/images/generate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({
                sessionId: this.sessionId,
                prompt,
                clientMessageId: metadata.userMessageId,
                assistantMessageId: metadata.id,
                size: "1024*1024",
                count: 1,
            }),
            signal: this.activeAbortController.signal,
        });
        const result = await this.readJsonResponse(response);
        const answer = result.data?.answer || "图片已生成";
        this.updateMessage(messageElement, answer);
        this.recordAssistantHistory(messageElement, answer, {
            ...metadata,
            prompt,
            generatedImages: result.data?.images || [],
        });
    }

    async persistAssistantMessage(content, metadata = {}, extraMetadata = {}) {
        if (!content) return;
        try {
            const response = await fetch(
                `${this.apiBaseUrl}/chat/sessions/${encodeURIComponent(this.sessionId)}/messages`,
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    credentials: "include",
                    body: JSON.stringify({
                        role: "assistant",
                        content,
                        clientMessageId: metadata.id,
                        metadata: {
                            prompt: metadata.prompt,
                            model: metadata.model,
                            retryOf: metadata.retryOf,
                            ...extraMetadata,
                        },
                    }),
                }
            );
            await this.readJsonResponse(response);
        } catch (error) {
            console.error("保存助手消息失败:", error);
        }
    }

    createTypewriter(messageElement) {
        let displayed = "";
        let target = "";
        let timer = null;
        let finishResolve = null;
        let finishing = false;
        let stopped = false;

        const scheduleNextTick = () => {
            const remaining = Math.max(1, target.length - displayed.length);
            timer = window.setTimeout(tick, this.getTypewriterDelayMs(remaining, finishing));
        };

        const tick = () => {
            if (stopped) return;
            if (displayed.length < target.length) {
                const remaining = target.length - displayed.length;
                const nextChunkSize = this.getTypewriterChunkSize(remaining, finishing);
                displayed += target.slice(
                    displayed.length,
                    displayed.length + nextChunkSize
                );
                this.updateMessage(messageElement, displayed, true);
                scheduleNextTick();
                return;
            }

            timer = null;
            if (finishResolve) {
                const resolve = finishResolve;
                finishResolve = null;
                resolve();
            }
        };

        const ensureRunning = () => {
            if (!timer && !stopped) {
                scheduleNextTick();
            }
        };

        return {
            push: (text) => {
                if (!text) return;
                target += text;
                ensureRunning();
            },
            finish: async (finalText) => {
                if (stopped) return;
                finishing = true;
                if (typeof finalText === "string" && finalText.length > target.length) {
                    target = finalText;
                    ensureRunning();
                }
                if (displayed.length < target.length) {
                    await new Promise((resolve) => {
                        finishResolve = resolve;
                        ensureRunning();
                    });
                }
                if (stopped) return;
                this.updateMessage(messageElement, finalText || target || displayed, false);
            },
            stop: () => {
                stopped = true;
                if (timer) {
                    window.clearTimeout(timer);
                    timer = null;
                }
                if (finishResolve) {
                    const resolve = finishResolve;
                    finishResolve = null;
                    resolve();
                }
                return displayed;
            },
        };
    }

    getTypewriterChunkSize(remaining, finishing = false) {
        if (remaining <= 1) return 1;
        const divisor = finishing
            ? this.typewriterFinishingBacklogDivisor
            : this.typewriterBacklogDivisor;
        const minChunkSize = finishing
            ? this.typewriterFinishingMinChunkSize
            : this.typewriterMinChunkSize;
        const maxChunkSize = finishing
            ? this.typewriterFinishingMaxChunkSize
            : this.typewriterMaxChunkSize;
        const adaptiveSize = Math.ceil(remaining / divisor);
        return Math.max(
            minChunkSize,
            Math.min(maxChunkSize, adaptiveSize)
        );
    }

    getTypewriterDelayMs(remaining, finishing = false) {
        if (finishing) {
            if (remaining >= 720) return this.typewriterFastDelayMs;
            if (remaining >= 180) return this.typewriterMediumDelayMs;
            return this.typewriterDelayMs;
        }
        if (remaining >= 360) return this.typewriterFastDelayMs;
        if (remaining >= 96) return this.typewriterMediumDelayMs;
        return this.typewriterDelayMs;
    }

    async triggerCreationDiagnosis() {
        if (!this.hasAIOpsAccess()) {
            this.showNotification("仅超级管理员可使用 AIOps 功能", "warning");
            return;
        }
        if (this.isStreaming) {
            this.showNotification("请等待当前任务完成", "warning");
            return;
        }

        const prompt = [
            "请结合当前会话历史，对当前 AI 视频提示词创作内容进行一次智能诊断。",
            "重点检查：人物一致性、剧情冲突、场景逻辑、分镜节奏、表情动作是否具体、提示词是否可直接用于 AI 真人视频或写实视频生产。",
            "如果当前会话里没有足够的剧情、角色或提示词内容，请先明确说明资料不足，并告诉用户需要补充哪些内容。",
            "请输出可直接落地的优化建议和改写示例。",
        ].join("\n");
        const userMessage = this.addMessage("user", prompt);
        const assistantMetadata = {
            id: this.generateMessageId(),
            prompt,
            userMessageId: userMessage.dataset.messageId,
        };
        const assistantMessage = this.addMessage(
            "assistant",
            "火宝正在检查创作方案...",
            false,
            true,
            assistantMetadata
        );
        this.isStreaming = true;
        this.stopRequested = false;
        this.updateUI();

        try {
            await this.sendStreamMessage(prompt, assistantMessage, assistantMetadata);
        } catch (error) {
            if (this.stopRequested || error.name === "AbortError") {
                this.updateMessage(assistantMessage, "已停止诊断");
            } else {
                this.updateMessage(assistantMessage, `创作诊断失败：${error.message}`);
            }
        } finally {
            this.activeAbortController = null;
            this.isStreaming = false;
            this.stopRequested = false;
            this.updateUI();
            this.saveCurrentChat();
        }
    }

    async handleFileSelect(event) {
        const file = event.target.files?.[0];
        if (!file) return;

        const formData = new FormData();
        formData.append("file", file);
        this.showUploadOverlay(true, file.name);

        try {
            const response = await fetch(`${this.apiBaseUrl}/upload`, {
                method: "POST",
                credentials: "include",
                body: formData,
            });
            await this.readJsonResponse(response);
            this.showNotification("文件已上传并开始构建知识索引", "success");
        } catch (error) {
            this.showNotification(error.message || "文件上传失败", "error");
        } finally {
            this.showUploadOverlay(false);
            event.target.value = "";
        }
    }

    handleImageSelect(event) {
        const files = Array.from(event.target.files || []);
        if (!files.length) return;

        const availableSlots = this.imageUploadMaxCount - this.pendingImages.length;
        if (availableSlots <= 0) {
            this.showNotification(`一次最多上传 ${this.imageUploadMaxCount} 张图片`, "warning");
            event.target.value = "";
            return;
        }

        files.slice(0, availableSlots).forEach((file) => {
            if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
                this.showNotification("图片格式仅支持 PNG、JPG、WEBP", "warning");
                return;
            }
            if (file.size > this.imageUploadMaxSize) {
                this.showNotification("单张图片不能超过 10MB", "warning");
                return;
            }
            this.pendingImages.push({
                id: this.generateMessageId(),
                file,
                previewUrl: URL.createObjectURL(file),
            });
        });

        if (files.length > availableSlots) {
            this.showNotification(`已保留前 ${availableSlots} 张图片`, "warning");
        }
        if (this.pendingImages.length) {
            this.selectMode("vision");
            this.renderPendingImages();
        }
        event.target.value = "";
    }

    renderPendingImages() {
        if (!this.inputWrapper) return;
        let tray = this.inputWrapper.querySelector(".image-preview-tray");
        if (!this.pendingImages.length) {
            tray?.remove();
            return;
        }
        if (!tray) {
            tray = document.createElement("div");
            tray.className = "image-preview-tray";
            this.inputWrapper.prepend(tray);
        }
        tray.innerHTML = "";
        this.pendingImages.forEach((image) => {
            const item = document.createElement("div");
            item.className = "image-preview-item";
            item.innerHTML = `
                <img src="${image.previewUrl}" alt="${this.escapeHtml(image.file.name)}">
                <button type="button" class="image-preview-remove" aria-label="移除图片" title="移除图片">
                    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M18 6L6 18M6 6L18 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                    </svg>
                </button>
            `;
            item.querySelector(".image-preview-remove")?.addEventListener("click", () => {
                this.removePendingImage(image.id);
            });
            tray.appendChild(item);
        });
    }

    removePendingImage(imageId) {
        const image = this.pendingImages.find((item) => item.id === imageId);
        if (image?.previewUrl) URL.revokeObjectURL(image.previewUrl);
        this.pendingImages = this.pendingImages.filter((item) => item.id !== imageId);
        this.renderPendingImages();
    }

    clearPendingImages(revokeUrls = true) {
        if (revokeUrls) {
            this.pendingImages.forEach((image) => {
                if (image.previewUrl) URL.revokeObjectURL(image.previewUrl);
            });
        }
        this.pendingImages = [];
        this.renderPendingImages();
    }

    addMessage(type, content, save = true, loading = false, metadata = {}) {
        const shouldScroll = this.shouldAutoScroll;
        const message = document.createElement("div");
        message.className = `message ${type === "user" ? "user" : "assistant"}`;
        const historyMessage = save ? this.createHistoryMessage(type, content, metadata) : null;
        message.dataset.messageId = historyMessage?.id || metadata.id || this.generateMessageId();
        message.dataset.content = content || "";
        if (metadata.prompt) message.dataset.prompt = metadata.prompt;
        if (metadata.modelPrompt) message.dataset.modelPrompt = metadata.modelPrompt;
        if (metadata.model) message.dataset.model = metadata.model;
        if (metadata.modelDisplayName) message.dataset.modelDisplayName = metadata.modelDisplayName;
        if (metadata.modelProvider) message.dataset.modelProvider = metadata.modelProvider;
        if (metadata.promptTemplate) message.dataset.promptTemplate = metadata.promptTemplate;
        if (metadata.feedback) message.dataset.feedback = metadata.feedback;
        if (metadata.retryOf) message.dataset.retryOf = metadata.retryOf;

        if (type !== "user") {
            const avatar = document.createElement("div");
            avatar.className = "message-avatar";
            avatar.innerHTML = `
                <img src="/static/assets/huobao-tx.png?v=20260514-tx" alt="火宝 AI">
            `;
            message.appendChild(avatar);
        }

        const wrapper = document.createElement("div");
        wrapper.className = "message-content-wrapper";

        const body = document.createElement("div");
        body.className = "message-content";
        message._contentBody = body;
        if (loading) {
            body.classList.add("streaming", "streaming-plain");
            body.textContent = content || "";
        } else if (type === "user") {
            body.innerHTML = this.escapeHtml(content);
        } else {
            body.innerHTML = this.renderMarkdown(content);
        }

        const time = document.createElement("div");
        time.className = "message-time";
        time.textContent = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });

        const imageGrid = this.createMessageImageGrid(type, metadata);
        if (imageGrid) {
            wrapper.appendChild(imageGrid);
        }
        wrapper.appendChild(body);
        wrapper.appendChild(time);
        if (type !== "user") {
            const actions = this.createAssistantActions(message);
            message._actionsElement = actions;
            wrapper.appendChild(actions);
        }
        message.appendChild(wrapper);
        this.chatMessages?.appendChild(message);
        if (type !== "user" && !loading) {
            this.highlightCodeBlocks(body);
            this.enhancePromptCopySections(body, message);
        }
        this.updateAssistantActions(message, loading);
        this.scrollToBottom(shouldScroll);
        this.checkAndSetCentered();

        if (save) {
            this.currentChatHistory.push(historyMessage);
        }
        return message;
    }

    updateMessage(messageElement, content, streaming = false) {
        const body = this.getMessageContentBody(messageElement);
        if (!body) return;
        const shouldScroll = this.shouldAutoScroll;
        body.classList.toggle("streaming", streaming);
        body.classList.toggle("streaming-plain", streaming);
        if (streaming) {
            body.textContent = content || "";
        } else {
            body.innerHTML = this.renderMarkdown(content);
            messageElement.dataset.content = content || "";
        }
        if (!streaming) {
            this.highlightCodeBlocks(body);
            this.enhancePromptCopySections(body, messageElement);
        }
        this.updateAssistantActions(messageElement, streaming);
        this.scrollToBottom(shouldScroll);
    }

    createMessageImageGrid(type, metadata = {}) {
        const images = this.getMessageImages(type, metadata);
        if (!images.length) return null;

        const grid = document.createElement("div");
        grid.className = "message-image-grid";
        images.forEach((image) => {
            const url = image.previewUrl || image.fileUrl || image.url;
            const safeUrl = this.isSafeUrl(url, { allowBlob: true, allowDataImages: true });
            if (!safeUrl) return;
            const item = document.createElement("a");
            item.className = "message-image-item";
            item.href = safeUrl;
            item.target = "_blank";
            item.rel = "noopener noreferrer";

            const img = document.createElement("img");
            img.src = safeUrl;
            img.alt = image.name || image.fileName || "image";
            item.appendChild(img);
            grid.appendChild(item);
        });
        return grid.children.length ? grid : null;
    }

    getMessageImages(type, metadata = {}) {
        if (type !== "user") return [];
        if (Array.isArray(metadata.images)) return metadata.images;
        if (Array.isArray(metadata.attachments)) {
            return metadata.attachments.filter((attachment) => {
                const mimeType = attachment.mimeType || "";
                return mimeType.startsWith("image/") || attachment.purpose === "vision";
            });
        }
        return [];
    }

    createAssistantActions(messageElement) {
        const actions = document.createElement("div");
        actions.className = "message-actions";
        actions.innerHTML = `
            <button type="button" class="message-action-btn message-action-more" data-action="more" title="更多操作" aria-label="更多操作">
                <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <circle cx="5" cy="12" r="1.6" fill="currentColor"/>
                    <circle cx="12" cy="12" r="1.6" fill="currentColor"/>
                    <circle cx="19" cy="12" r="1.6" fill="currentColor"/>
                </svg>
            </button>
            <button type="button" class="message-action-btn" data-action="copy" title="复制消息" aria-label="复制消息">
                <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect x="9" y="9" width="11" height="11" rx="2" stroke="currentColor" stroke-width="1.8"/>
                    <path d="M5 15H4C2.89543 15 2 14.1046 2 13V4C2 2.89543 2.89543 2 4 2H13C14.1046 2 15 2.89543 15 4V5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                </svg>
            </button>
            <button type="button" class="message-action-btn" data-action="like" title="喜欢" aria-label="喜欢">
                <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M7 22H4C2.89543 22 2 21.1046 2 20V13C2 11.8954 2.89543 11 4 11H7M7 22V11M7 22H17.1132C18.7206 22 20.1099 20.8795 20.4467 19.3078L21.9467 12.3078C22.3636 10.362 20.8794 8.5 18.8895 8.5H15L15.6716 4.47033C15.8532 3.38052 15.0139 2.39284 13.9092 2.39284C13.3405 2.39284 12.8005 2.64608 12.4364 3.083L7 9.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </button>
            <button type="button" class="message-action-btn" data-action="dislike" title="不喜欢" aria-label="不喜欢">
                <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M17 2H20C21.1046 2 22 2.89543 22 4V11C22 12.1046 21.1046 13 20 13H17M17 2V13M17 2H6.88679C5.27941 2 3.89006 3.12055 3.55327 4.69216L2.05327 11.6922C1.63636 13.638 3.12061 15.5 5.11048 15.5H9L8.32843 19.5297C8.14679 20.6195 8.98613 21.6072 10.0908 21.6072C10.6595 21.6072 11.1995 21.3539 11.5636 20.917L17 14.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </button>
            <button type="button" class="message-action-btn" data-action="retry" title="重新生成" aria-label="重新生成">
                <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M20 11A8.1 8.1 0 0 0 5.5 6L4 8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                    <path d="M4 4V8H8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                    <path d="M4 13A8.1 8.1 0 0 0 18.5 18L20 16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                    <path d="M20 20V16H16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </button>
        `;

        actions.querySelector('[data-action="more"]')?.addEventListener("click", (event) => {
            event.stopPropagation();
            const willOpen = !actions.classList.contains("mobile-actions-open");
            this.closeMobileMessageActions(actions);
            actions.classList.toggle("mobile-actions-open", willOpen);
        });
        actions.querySelector('[data-action="copy"]')?.addEventListener("click", () => {
            this.copyAssistantMessage(messageElement);
            this.closeMobileMessageActions();
        });
        actions.querySelector('[data-action="like"]')?.addEventListener("click", () => {
            this.toggleAssistantFeedback(messageElement, "like");
            this.closeMobileMessageActions();
        });
        actions.querySelector('[data-action="dislike"]')?.addEventListener("click", () => {
            this.toggleAssistantFeedback(messageElement, "dislike");
            this.closeMobileMessageActions();
        });
        actions.querySelector('[data-action="retry"]')?.addEventListener("click", () => {
            this.retryAssistantMessage(messageElement);
            this.closeMobileMessageActions();
        });

        return actions;
    }

    updateAssistantActions(messageElement, streaming = false) {
        if (!messageElement.classList.contains("assistant")) return;
        const actions = this.getMessageActions(messageElement);
        if (!actions) return;

        const feedback = messageElement.dataset.feedback || "";
        const canRetry = !this.isStreaming && Boolean(this.getMessagePrompt(messageElement));
        const stateKey = `${streaming ? 1 : 0}|${feedback}|${canRetry ? 1 : 0}`;
        if (actions.dataset.stateKey === stateKey) return;

        actions.dataset.stateKey = stateKey;
        actions.hidden = streaming;
        const retryButton = actions.querySelector('[data-action="retry"]');
        actions.querySelector('[data-action="like"]')?.classList.toggle("active", feedback === "like");
        actions.querySelector('[data-action="dislike"]')?.classList.toggle("active", feedback === "dislike");
        actions.classList.toggle("has-feedback", Boolean(feedback));
        if (retryButton) {
            retryButton.disabled = !canRetry;
        }
    }

    updateAllAssistantActions() {
        this.chatMessages?.querySelectorAll(".message.assistant").forEach((messageElement) => {
            const isStreaming = this.getMessageContentBody(messageElement)?.classList.contains("streaming");
            this.updateAssistantActions(messageElement, Boolean(isStreaming));
        });
    }

    async copyAssistantMessage(messageElement) {
        const text = this.getAssistantMessageText(messageElement);
        if (!text) return;

        await this.copyTextToClipboard(text);
    }

    async copyPromptSectionFromMessage(messageElement, titleText, button) {
        const source = messageElement.dataset.content || this.getAssistantMessageText(messageElement);
        const text = this.extractPromptSectionText(source, titleText);
        if (!text) return;

        const copied = await this.copyTextToClipboard(text, "已复制提示词");
        if (!button || !copied) return;

        const previousLabel = button.querySelector("span")?.textContent || "";
        button.classList.add("copied");
        const label = button.querySelector("span");
        if (label) label.textContent = "已复制";
        window.setTimeout(() => {
            button.classList.remove("copied");
            if (label) label.textContent = previousLabel || "复制";
        }, 1400);
    }

    async copyTextToClipboard(text, successMessage = "已复制") {
        let copied = false;
        try {
            await navigator.clipboard.writeText(text);
            copied = true;
        } catch (error) {
            copied = this.copyTextWithFallback(text);
        }
        this.showNotification(copied ? successMessage : "复制失败", copied ? "success" : "error");
        return copied;
    }

    copyTextWithFallback(text) {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        const copied = document.execCommand("copy");
        textarea.remove();
        return copied;
    }

    getAssistantMessageText(messageElement) {
        return this.getMessageContentBody(messageElement)?.innerText.trim() || "";
    }

    enhancePromptCopySections(container, messageElement) {
        if (!container || !messageElement) return;

        const titlePattern = /【(?:示例提示词(?:[:：][^】]*)?|优化后提示词)】/;
        const titleElements = Array.from(container.querySelectorAll("p, h1, h2, h3, h4, h5, h6"))
            .map((element) => {
                const match = element.textContent.trim().match(titlePattern);
                return match && match.index === 0 ? { element, title: match[0] } : null;
            })
            .filter(Boolean);

        titleElements.forEach(({ element, title }) => {
            if (element.querySelector(".prompt-copy-btn")) return;
            if (!this.extractPromptSectionText(messageElement.dataset.content || "", title)) return;

            element.classList.add("prompt-section-title");
            const button = document.createElement("button");
            button.type = "button";
            button.className = "prompt-copy-btn";
            button.title = "复制所有示例提示词";
            button.setAttribute("aria-label", "复制所有示例提示词");
            button.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                    <rect x="9" y="9" width="11" height="11" rx="2" stroke="currentColor" stroke-width="1.8"/>
                    <path d="M5 15H4C2.89543 15 2 14.1046 2 13V4C2 2.89543 2.89543 2 4 2H13C14.1046 2 15 2.89543 15 4V5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                </svg>
                <span>复制</span>
            `;
            button.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                this.copyPromptSectionFromMessage(messageElement, title, button);
            });
            element.appendChild(button);
        });
    }

    extractPromptSectionText(source, titleText) {
        const text = (source || "").replace(/\r\n/g, "\n").trim();
        if (!text || !titleText) return "";

        let start = text.indexOf(titleText);
        if (start < 0) {
            const fallbackMatch = text.match(/【(?:示例提示词(?:[:：][^】]*)?|优化后提示词)】/);
            if (!fallbackMatch) return "";
            start = fallbackMatch.index;
        }

        const rest = text.slice(start);
        const nextHeading = rest.slice(titleText.length).match(/\n\s*【(?!正向提示词|负面提示词)[^】]+】/);
        const section = nextHeading
            ? rest.slice(0, titleText.length + nextHeading.index)
            : rest;
        return section.trim();
    }

    toggleAssistantFeedback(messageElement, feedback) {
        const historyMessage = this.findHistoryMessageById(messageElement.dataset.messageId);
        if (!historyMessage) return;

        const nextFeedback = historyMessage.feedback === feedback ? "" : feedback;
        if (nextFeedback) {
            historyMessage.feedback = nextFeedback;
            historyMessage.feedbackUpdatedAt = new Date().toISOString();
            messageElement.dataset.feedback = nextFeedback;
        } else {
            delete historyMessage.feedback;
            delete historyMessage.feedbackUpdatedAt;
            delete messageElement.dataset.feedback;
        }

        this.updateAssistantActions(messageElement);
        this.saveCurrentChat();
        const notificationText =
            nextFeedback === "like" ? "已记录喜欢" : nextFeedback === "dislike" ? "已记录反馈" : "已取消反馈";
        this.showNotification(notificationText, "success");
    }

    async retryAssistantMessage(messageElement) {
        if (this.isStreaming) {
            this.showNotification("请等待当前回答完成", "warning");
            return;
        }

        const prompt = this.getMessagePrompt(messageElement);
        if (!prompt) {
            this.showNotification("暂时无法重试这条消息", "warning");
            return;
        }
        const modelPrompt = this.getMessageModelPrompt(messageElement) || prompt;
        const model = this.getMessageModel(messageElement) || this.getCurrentModel();

        const assistantMetadata = {
            id: this.generateMessageId(),
            prompt,
            modelPrompt,
            model,
            promptTemplate: messageElement.dataset.promptTemplate,
            retryOf: messageElement.dataset.messageId,
        };
        const retryMessage = this.addMessage("assistant", "火宝正在重新生成...", false, true, assistantMetadata);
        this.isStreaming = true;
        this.stopRequested = false;
        this.updateUI();

        try {
            if (this.currentMode === "stream") {
                await this.sendStreamMessage(prompt, retryMessage, assistantMetadata);
            } else {
                await this.sendQuickMessage(prompt, retryMessage, assistantMetadata);
            }
        } catch (error) {
            if (this.stopRequested || error.name === "AbortError") {
                this.updateMessage(retryMessage, "已停止生成");
            } else {
                this.updateMessage(retryMessage, `抱歉，处理时出现错误：${error.message}`);
                this.showNotification(error.message || "请求失败", "error");
            }
        } finally {
            this.activeAbortController = null;
            this.activeTypewriter = null;
            this.isStreaming = false;
            this.stopRequested = false;
            this.updateUI();
            this.saveCurrentChat();
        }
    }

    getMessagePrompt(messageElement) {
        if (messageElement.dataset.prompt) return messageElement.dataset.prompt;
        return this.findHistoryMessageById(messageElement.dataset.messageId)?.prompt || "";
    }

    getMessageModelPrompt(messageElement) {
        if (messageElement.dataset.modelPrompt) return messageElement.dataset.modelPrompt;
        return this.findHistoryMessageById(messageElement.dataset.messageId)?.modelPrompt || "";
    }

    getMessageModel(messageElement) {
        if (messageElement.dataset.model) return messageElement.dataset.model;
        return this.findHistoryMessageById(messageElement.dataset.messageId)?.model || "";
    }

    findHistoryMessageById(messageId) {
        if (!messageId) return null;
        return this.currentChatHistory.find((message) => message.id === messageId) || null;
    }

    createHistoryMessage(type, content, metadata = {}) {
        const message = {
            id: metadata.id || this.generateMessageId(),
            type,
            content,
            timestamp: metadata.timestamp || new Date().toISOString(),
        };
        if (metadata.prompt) message.prompt = metadata.prompt;
        if (metadata.modelPrompt) message.modelPrompt = metadata.modelPrompt;
        if (metadata.model) message.model = metadata.model;
        if (metadata.modelDisplayName) message.modelDisplayName = metadata.modelDisplayName;
        if (metadata.modelProvider) message.modelProvider = metadata.modelProvider;
        if (metadata.promptTemplate) message.promptTemplate = metadata.promptTemplate;
        if (metadata.feedback) message.feedback = metadata.feedback;
        if (metadata.feedbackUpdatedAt) message.feedbackUpdatedAt = metadata.feedbackUpdatedAt;
        if (metadata.retryOf) message.retryOf = metadata.retryOf;
        if (Array.isArray(metadata.images)) message.images = metadata.images;
        if (Array.isArray(metadata.attachments)) message.attachments = metadata.attachments;
        if (Array.isArray(metadata.generatedImages)) message.generatedImages = metadata.generatedImages;
        return message;
    }

    recordAssistantHistory(messageElement, content, metadata = {}) {
        const historyMessage = this.createHistoryMessage("assistant", content, {
            ...metadata,
            id: metadata.id || messageElement.dataset.messageId,
            prompt: metadata.prompt || messageElement.dataset.prompt,
            modelPrompt: metadata.modelPrompt || messageElement.dataset.modelPrompt,
            model: metadata.model || messageElement.dataset.model,
            promptTemplate: metadata.promptTemplate || messageElement.dataset.promptTemplate,
        });
        this.currentChatHistory.push(historyMessage);
        messageElement.dataset.messageId = historyMessage.id;
        if (historyMessage.prompt) messageElement.dataset.prompt = historyMessage.prompt;
        if (historyMessage.modelPrompt) messageElement.dataset.modelPrompt = historyMessage.modelPrompt;
        if (historyMessage.model) messageElement.dataset.model = historyMessage.model;
        if (historyMessage.promptTemplate) messageElement.dataset.promptTemplate = historyMessage.promptTemplate;
        if (historyMessage.retryOf) messageElement.dataset.retryOf = historyMessage.retryOf;
        this.updateAssistantActions(messageElement);
    }

    normalizeHistoryMessages(messages = []) {
        let lastUserPrompt = "";
        return messages.map((message) => {
            const normalizedMessage = this.createHistoryMessage(message.type, message.content, message);
            if (normalizedMessage.type === "user") {
                lastUserPrompt = normalizedMessage.content;
            } else if (normalizedMessage.type === "assistant" && !normalizedMessage.prompt && lastUserPrompt) {
                normalizedMessage.prompt = lastUserPrompt;
            }
            return normalizedMessage;
        });
    }

    renderMarkdown(content) {
        const text = content || "";
        const cachedHtml = this.getCachedMarkdownHtml(text);
        if (cachedHtml !== null) {
            return cachedHtml;
        }
        if (typeof marked === "undefined") {
            return this.escapeHtml(text);
        }
        try {
            const rendered = this.sanitizeMarkdownHtml(marked.parse(text));
            this.setCachedMarkdownHtml(text, rendered);
            return rendered;
        } catch (error) {
            console.error("Markdown 渲染失败:", error);
            return this.escapeHtml(text);
        }
    }

    getCachedMarkdownHtml(content) {
        if (!content) return null;
        const cached = this.markdownRenderCache.get(content);
        if (typeof cached !== "string") return null;
        this.markdownRenderCache.delete(content);
        this.markdownRenderCache.set(content, cached);
        return cached;
    }

    setCachedMarkdownHtml(content, html) {
        if (!content || typeof html !== "string") return;
        if (this.markdownRenderCache.has(content)) {
            this.markdownRenderCache.delete(content);
        }
        this.markdownRenderCache.set(content, html);
        while (this.markdownRenderCache.size > this.markdownRenderCacheMaxEntries) {
            const oldestKey = this.markdownRenderCache.keys().next().value;
            if (typeof oldestKey !== "string") break;
            this.markdownRenderCache.delete(oldestKey);
        }
    }

    sanitizeMarkdownHtml(html) {
        const template = document.createElement("template");
        template.innerHTML = html || "";

        const allowedTags = new Set([
            "A",
            "BLOCKQUOTE",
            "BR",
            "CODE",
            "DEL",
            "EM",
            "H1",
            "H2",
            "H3",
            "H4",
            "H5",
            "H6",
            "HR",
            "IMG",
            "LI",
            "OL",
            "P",
            "PRE",
            "S",
            "SPAN",
            "STRONG",
            "TABLE",
            "TBODY",
            "TD",
            "TH",
            "THEAD",
            "TR",
            "UL",
        ]);
        const blockedTags = new Set([
            "AUDIO",
            "BUTTON",
            "CANVAS",
            "EMBED",
            "FORM",
            "IFRAME",
            "INPUT",
            "LINK",
            "MATH",
            "META",
            "OBJECT",
            "SCRIPT",
            "SELECT",
            "SOURCE",
            "STYLE",
            "SVG",
            "TEXTAREA",
            "VIDEO",
        ]);
        const allowedAttributes = {
            A: new Set(["href", "title"]),
            CODE: new Set(["class"]),
            IMG: new Set(["alt", "height", "src", "title", "width"]),
            LI: new Set(["value"]),
            OL: new Set(["start"]),
            PRE: new Set(["class"]),
            SPAN: new Set(["class"]),
            TD: new Set(["align", "colspan", "rowspan"]),
            TH: new Set(["align", "colspan", "rowspan"]),
        };

        this.sanitizeHtmlNode(template.content, allowedTags, allowedAttributes, blockedTags);
        return template.innerHTML;
    }

    sanitizeHtmlNode(node, allowedTags, allowedAttributes, blockedTags) {
        Array.from(node.childNodes).forEach((child) => {
            if (child.nodeType === Node.TEXT_NODE) return;
            if (child.nodeType !== Node.ELEMENT_NODE) {
                child.remove();
                return;
            }

            const tagName = child.tagName;
            if (blockedTags.has(tagName)) {
                child.remove();
                return;
            }

            this.sanitizeHtmlNode(child, allowedTags, allowedAttributes, blockedTags);
            if (!allowedTags.has(tagName)) {
                child.replaceWith(...Array.from(child.childNodes));
                return;
            }

            this.sanitizeElementAttributes(child, allowedAttributes);
        });
    }

    sanitizeElementAttributes(element, allowedAttributes) {
        const tagName = element.tagName;
        const tagAttributes = allowedAttributes[tagName] || new Set();

        Array.from(element.attributes).forEach((attribute) => {
            const name = attribute.name.toLowerCase();
            if (name.startsWith("on") || name === "style" || name === "srcdoc" || !tagAttributes.has(name)) {
                element.removeAttribute(attribute.name);
            }
        });

        if (tagName === "A") {
            const href = element.getAttribute("href");
            const safeHref = this.isSafeUrl(href);
            if (safeHref) {
                element.href = safeHref;
                element.target = "_blank";
                element.rel = "noopener noreferrer";
            } else {
                element.removeAttribute("href");
                element.removeAttribute("target");
                element.removeAttribute("rel");
            }
        }

        if (tagName === "IMG") {
            const src = element.getAttribute("src");
            const safeSrc = this.isSafeUrl(src);
            if (!safeSrc) {
                element.remove();
                return;
            }
            element.src = safeSrc;
            element.loading = "lazy";
        }

        ["height", "start", "value", "width"].forEach((name) => {
            const value = element.getAttribute(name);
            if (value && !/^\d{1,4}$/.test(value)) element.removeAttribute(name);
        });

        ["colspan", "rowspan"].forEach((name) => {
            const value = element.getAttribute(name);
            if (value && !/^\d{1,2}$/.test(value)) element.removeAttribute(name);
        });

        const align = element.getAttribute("align");
        if (align && !["center", "left", "right"].includes(align.toLowerCase())) {
            element.removeAttribute("align");
        }
    }

    isSafeUrl(value, { allowBlob = false, allowDataImages = false } = {}) {
        if (typeof value !== "string") return "";
        const trimmed = value.trim();
        if (!trimmed || /[\u0000-\u001f\u007f]/.test(trimmed)) return "";

        if (allowDataImages && /^data:image\/(?:gif|jpe?g|png|webp);base64,[a-z0-9+/=]+$/i.test(trimmed)) {
            return trimmed;
        }

        try {
            const url = new URL(trimmed, window.location.origin);
            if (["http:", "https:", "mailto:", "tel:"].includes(url.protocol)) {
                return url.href;
            }
            if (allowBlob && url.protocol === "blob:" && url.origin === window.location.origin) {
                return url.href;
            }
        } catch (error) {
            return "";
        }

        return "";
    }

    highlightCodeBlocks(container) {
        if (typeof hljs === "undefined" || !container) return;
        container.querySelectorAll("pre code").forEach((block) => hljs.highlightElement(block));
    }

    async readJsonResponse(response) {
        const result = await response.json().catch(() => ({}));
        if (!response.ok || result.code >= 400) {
            if (response.status === 401) {
                window.location.href = "/login";
                return result;
            }
            throw new Error(result.message || response.statusText || "请求失败");
        }
        return result;
    }

    saveCurrentChat() {
        this.refreshChatHistories();
    }

    async loadChatHistoriesFromServer() {
        await this.refreshChatHistories();
    }

    async refreshChatHistories() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/chat/sessions`, {
                credentials: "include",
            });
            const result = await this.readJsonResponse(response);
            this.chatHistories = result.data?.sessions || [];
            this.renderChatHistory();
        } catch (error) {
            console.error("历史记录读取失败:", error);
        }
    }

    renderChatHistory() {
        if (!this.chatHistoryList) return;
        this.chatHistoryList.innerHTML = "";

        this.chatHistories.forEach((history) => {
            const item = document.createElement("div");
            item.className = "history-item";
            item.classList.toggle("active", history.id === this.sessionId);
            item.innerHTML = `
                <div class="history-item-content">
                    <span class="history-item-title">${this.escapeHtml(history.title)}</span>
                </div>
                <button class="history-item-delete" title="删除">
                    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M18 6L6 18M6 6L18 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                    </svg>
                </button>
            `;

            item.addEventListener("click", (event) => {
                if (event.target.closest(".history-item-delete")) return;
                this.closeMobileSidebar();
                this.loadChatHistory(history.id);
            });
            item.querySelector(".history-item-delete").addEventListener("click", (event) => {
                event.stopPropagation();
                this.deleteChatHistory(history.id);
            });
            this.chatHistoryList.appendChild(item);
        });
    }

    async loadChatHistory(historyId) {
        const history = this.chatHistories.find((item) => item.id === historyId);
        if (!history || this.isStreaming) return;
        try {
            const response = await fetch(`${this.apiBaseUrl}/chat/sessions/${encodeURIComponent(historyId)}/messages`, {
                credentials: "include",
            });
            const result = await this.readJsonResponse(response);
            this.sessionId = history.id;
            this.currentChatHistory = [];
            this.shouldAutoScroll = true;
            this.chatMessages.innerHTML = "";
            const normalizedMessages = this.normalizeHistoryMessages(result.data?.messages || []);
            normalizedMessages.forEach((message) => this.addMessage(message.type, message.content, false, false, message));
            this.currentChatHistory = normalizedMessages;
            this.renderChatHistory();
            this.scrollToBottom(true);
            this.checkAndSetCentered();
        } catch (error) {
            this.showNotification(error.message || "读取对话失败", "error");
        }
    }

    async deleteChatHistory(historyId) {
        if (this.isStreaming) return;
        try {
            const response = await fetch(`${this.apiBaseUrl}/chat/sessions/${encodeURIComponent(historyId)}`, {
                method: "DELETE",
                credentials: "include",
            });
            await this.readJsonResponse(response);
            this.chatHistories = this.chatHistories.filter((history) => history.id !== historyId);
            if (historyId === this.sessionId) {
                this.sessionId = this.generateSessionId();
                this.currentChatHistory = [];
                this.chatMessages.innerHTML = "";
                this.checkAndSetCentered();
            }
            this.renderChatHistory();
        } catch (error) {
            this.showNotification(error.message || "删除对话失败", "error");
        }
    }

    showNotification(message, type = "info") {
        const notification = document.createElement("div");
        notification.className = "notification";
        notification.textContent = message;
        const colors = {
            success: "rgba(34, 139, 87, 0.92)",
            warning: "rgba(191, 111, 19, 0.92)",
            error: "rgba(159, 17, 20, 0.92)",
            info: "rgba(24, 24, 27, 0.92)",
        };
        notification.style.background = colors[type] || colors.info;
        document.body.appendChild(notification);
        window.setTimeout(() => {
            notification.style.animation = "slideOut 0.28s ease forwards";
            window.setTimeout(() => notification.remove(), 280);
        }, 2600);
    }

    showUploadOverlay(show, fileName = "") {
        if (!this.loadingOverlay) return;
        this.loadingOverlay.style.display = show ? "flex" : "none";
        const title = this.loadingOverlay.querySelector(".loading-text");
        const subtitle = this.loadingOverlay.querySelector(".loading-subtext");
        if (title) title.textContent = show ? "正在上传并构建知识索引..." : "";
        if (subtitle) subtitle.textContent = fileName || "请稍候";
        document.body.style.overflow = show ? "hidden" : "";
    }

    checkAndSetCentered() {
        const hasVisibleMessages = Boolean(this.chatMessages?.querySelector(".message"));
        const hasHistoryMessages = this.currentChatHistory.length > 0;
        this.chatContainer?.classList.toggle("centered", !hasHistoryMessages && !hasVisibleMessages);
    }

    scrollToBottom(force = false) {
        if (!this.chatMessages || (!force && !this.shouldAutoScroll)) return;
        this.pendingScrollToBottom = true;
        this.shouldAutoScroll = true;
        if (this.scrollAnimationFrame) return;

        this.scrollAnimationFrame = window.requestAnimationFrame(() => {
            this.scrollAnimationFrame = 0;
            if (!this.chatMessages || !this.pendingScrollToBottom) return;
            this.pendingScrollToBottom = false;
            this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
        });
    }

    getMessageContentBody(messageElement) {
        if (!messageElement) return null;
        if (messageElement._contentBody?.isConnected) {
            return messageElement._contentBody;
        }
        const body = messageElement.querySelector(".message-content");
        if (body) {
            messageElement._contentBody = body;
        }
        return body;
    }

    getMessageActions(messageElement) {
        if (!messageElement) return null;
        if (messageElement._actionsElement?.isConnected) {
            return messageElement._actionsElement;
        }
        const actions = messageElement.querySelector(".message-actions");
        if (actions) {
            messageElement._actionsElement = actions;
        }
        return actions;
    }

    generateSessionId() {
        return `session-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    }

    generateMessageId() {
        return `message-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    }

    escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text || "";
        return div.innerHTML;
    }

    async logout() {
        try {
            await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
        } finally {
            window.location.href = "/login";
        }
    }
}

const style = document.createElement("style");
style.textContent = `
    @keyframes slideIn {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }

    @keyframes slideOut {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(100%); opacity: 0; }
    }
`;
document.head.appendChild(style);

async function ensureAuthenticated() {
    try {
        const response = await fetch("/api/auth/me", { credentials: "include" });
        if (response.ok) {
            const result = await response.json().catch(() => ({}));
            return result.data?.user || true;
        }
    } catch (error) {
        console.error("登录状态检查失败:", error);
    }
    window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname + window.location.search)}`;
    return false;
}

document.addEventListener("DOMContentLoaded", async () => {
    const currentUser = await ensureAuthenticated();
    if (currentUser) {
        new SuperBizAgentApp(currentUser === true ? null : currentUser);
    }
});
