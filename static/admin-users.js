class AdminApp {
    constructor() {
        this.currentAdmin = null;
        this.view = this.resolveView();
        this.state = {
            users: { page: 1, pageSize: 10, totalPages: 0, rows: [] },
            kb: { page: 1, pageSize: 10, totalPages: 0, rows: [] },
            prompts: { page: 1, pageSize: 10, totalPages: 0, rows: [] },
            models: { page: 1, pageSize: 10, totalPages: 0, rows: [] },
        };
        this.activeUser = null;
        this.activeDocument = null;
        this.activePrompt = null;
        this.activeModel = null;

        this.bindElements();
        this.bindEvents();
        this.init();
    }

    bindElements() {
        this.pageTitle = document.getElementById("pageTitle");
        this.currentAdminNode = document.getElementById("currentAdmin");
        this.logoutBtn = document.getElementById("logoutBtn");
        this.views = {
            users: document.getElementById("usersView"),
            kb: document.getElementById("kbView"),
            prompts: document.getElementById("promptsView"),
            models: document.getElementById("modelsView"),
        };
        this.drawerMask = document.getElementById("drawerMask");
        this.sideDrawer = document.getElementById("sideDrawer");
        this.drawerTitle = document.getElementById("drawerTitle");
        this.drawerBody = document.getElementById("drawerBody");
        this.drawerCloseBtn = document.getElementById("drawerCloseBtn");

        this.mobileFilter = document.getElementById("mobileFilter");
        this.roleFilter = document.getElementById("roleFilter");
        this.statusFilter = document.getElementById("statusFilter");
        this.levelFilter = document.getElementById("levelFilter");
        this.usersTbody = document.getElementById("usersTbody");
        this.usersEmpty = document.getElementById("usersEmpty");
        this.usersPageMeta = document.getElementById("usersPageMeta");
        this.usersPrevBtn = document.getElementById("usersPrevBtn");
        this.usersNextBtn = document.getElementById("usersNextBtn");
        this.userDialog = document.getElementById("userDialog");
        this.userForm = document.getElementById("userForm");
        this.userNickname = document.getElementById("userNickname");
        this.userRoleField = document.getElementById("userRoleField");
        this.userRole = document.getElementById("userRole");
        this.userStatus = document.getElementById("userStatus");
        this.userMessage = document.getElementById("userMessage");

        this.kbUploadForm = document.getElementById("kbUploadForm");
        this.kbUploadFile = document.getElementById("kbUploadFile");
        this.kbUploadCategory = document.getElementById("kbUploadCategory");
        this.kbUploadDescription = document.getElementById("kbUploadDescription");
        this.kbImportExistingBtn = document.getElementById("kbImportExistingBtn");
        this.kbUploadMessage = document.getElementById("kbUploadMessage");
        this.kbKeywordFilter = document.getElementById("kbKeywordFilter");
        this.kbCategoryFilter = document.getElementById("kbCategoryFilter");
        this.kbStatusFilter = document.getElementById("kbStatusFilter");
        this.kbEnabledFilter = document.getElementById("kbEnabledFilter");
        this.kbTbody = document.getElementById("kbTbody");
        this.kbEmpty = document.getElementById("kbEmpty");
        this.kbPageMeta = document.getElementById("kbPageMeta");
        this.kbPrevBtn = document.getElementById("kbPrevBtn");
        this.kbNextBtn = document.getElementById("kbNextBtn");
        this.kbDialog = document.getElementById("kbDialog");
        this.kbForm = document.getElementById("kbForm");
        this.kbEditTitle = document.getElementById("kbEditTitle");
        this.kbEditCategory = document.getElementById("kbEditCategory");
        this.kbEditDescription = document.getElementById("kbEditDescription");
        this.kbEditMessage = document.getElementById("kbEditMessage");
        this.kbContentDialog = document.getElementById("kbContentDialog");
        this.kbContentForm = document.getElementById("kbContentForm");
        this.kbContentTitle = document.getElementById("kbContentTitle");
        this.kbContentEditor = document.getElementById("kbContentEditor");
        this.kbContentReindex = document.getElementById("kbContentReindex");
        this.kbContentMessage = document.getElementById("kbContentMessage");
        this.kbSearchTestForm = document.getElementById("kbSearchTestForm");
        this.kbSearchQuery = document.getElementById("kbSearchQuery");
        this.kbSearchTopK = document.getElementById("kbSearchTopK");
        this.kbSearchCategory = document.getElementById("kbSearchCategory");
        this.kbSearchResults = document.getElementById("kbSearchResults");

        this.promptKeywordFilter = document.getElementById("promptKeywordFilter");
        this.promptTypeFilter = document.getElementById("promptTypeFilter");
        this.promptEnabledFilter = document.getElementById("promptEnabledFilter");
        this.promptsTbody = document.getElementById("promptsTbody");
        this.promptsEmpty = document.getElementById("promptsEmpty");
        this.promptsPageMeta = document.getElementById("promptsPageMeta");
        this.promptsPrevBtn = document.getElementById("promptsPrevBtn");
        this.promptsNextBtn = document.getElementById("promptsNextBtn");
        this.promptDialog = document.getElementById("promptDialog");
        this.promptDialogTitle = document.getElementById("promptDialogTitle");
        this.promptForm = document.getElementById("promptForm");
        this.promptKey = document.getElementById("promptKey");
        this.promptName = document.getElementById("promptName");
        this.promptType = document.getElementById("promptType");
        this.promptContent = document.getElementById("promptContent");
        this.promptRemark = document.getElementById("promptRemark");
        this.promptEnableOnCreateField = document.getElementById("promptEnableOnCreateField");
        this.promptEnableOnCreate = document.getElementById("promptEnableOnCreate");
        this.promptTestInput = document.getElementById("promptTestInput");
        this.promptTestBtn = document.getElementById("promptTestBtn");
        this.promptTestOutput = document.getElementById("promptTestOutput");
        this.promptMessage = document.getElementById("promptMessage");

        this.modelKeywordFilter = document.getElementById("modelKeywordFilter");
        this.modelEnabledFilter = document.getElementById("modelEnabledFilter");
        this.modelsTbody = document.getElementById("modelsTbody");
        this.modelsEmpty = document.getElementById("modelsEmpty");
        this.modelsPageMeta = document.getElementById("modelsPageMeta");
        this.modelsPrevBtn = document.getElementById("modelsPrevBtn");
        this.modelsNextBtn = document.getElementById("modelsNextBtn");
        this.modelDialog = document.getElementById("modelDialog");
        this.modelDialogTitle = document.getElementById("modelDialogTitle");
        this.modelForm = document.getElementById("modelForm");
        this.modelDisplayName = document.getElementById("modelDisplayName");
        this.modelId = document.getElementById("modelId");
        this.modelProvider = document.getElementById("modelProvider");
        this.modelSortOrder = document.getElementById("modelSortOrder");
        this.modelEnabled = document.getElementById("modelEnabled");
        this.modelDefault = document.getElementById("modelDefault");
        this.modelRemark = document.getElementById("modelRemark");
        this.modelMessage = document.getElementById("modelMessage");
    }

    bindEvents() {
        this.logoutBtn.addEventListener("click", () => this.logout());
        this.drawerMask.addEventListener("click", () => this.closeDrawer());
        this.drawerCloseBtn.addEventListener("click", () => this.closeDrawer());
        document.querySelectorAll("[data-close-dialog]").forEach((button) => {
            button.addEventListener("click", () => document.getElementById(button.dataset.closeDialog).close());
        });

        document.getElementById("userSearchBtn").addEventListener("click", () => {
            this.state.users.page = 1;
            this.loadUsers();
        });
        document.getElementById("userResetBtn").addEventListener("click", () => this.resetUsers());
        this.usersPrevBtn.addEventListener("click", () => this.changePage("users", -1));
        this.usersNextBtn.addEventListener("click", () => this.changePage("users", 1));
        this.usersTbody.addEventListener("click", (event) => this.handleUserAction(event));
        this.userForm.addEventListener("submit", (event) => {
            event.preventDefault();
            this.saveUser();
        });

        this.kbUploadForm.addEventListener("submit", (event) => {
            event.preventDefault();
            this.uploadKbDocument();
        });
        this.kbImportExistingBtn.addEventListener("click", () => this.importExistingKbDocuments());
        document.getElementById("kbSearchBtn").addEventListener("click", () => {
            this.state.kb.page = 1;
            this.loadKbDocuments();
        });
        document.getElementById("kbResetBtn").addEventListener("click", () => this.resetKb());
        this.kbPrevBtn.addEventListener("click", () => this.changePage("kb", -1));
        this.kbNextBtn.addEventListener("click", () => this.changePage("kb", 1));
        this.kbTbody.addEventListener("click", (event) => this.handleKbAction(event));
        this.kbForm.addEventListener("submit", (event) => {
            event.preventDefault();
            this.saveKbDocument();
        });
        this.kbContentForm.addEventListener("submit", (event) => {
            event.preventDefault();
            this.saveKbContent();
        });
        this.kbSearchTestForm.addEventListener("submit", (event) => {
            event.preventDefault();
            this.runKbSearchTest();
        });

        document.getElementById("promptSearchBtn").addEventListener("click", () => {
            this.state.prompts.page = 1;
            this.loadPrompts();
        });
        document.getElementById("promptResetBtn").addEventListener("click", () => this.resetPrompts());
        document.getElementById("promptNewBtn").addEventListener("click", () => this.openPromptEditor());
        this.promptsPrevBtn.addEventListener("click", () => this.changePage("prompts", -1));
        this.promptsNextBtn.addEventListener("click", () => this.changePage("prompts", 1));
        this.promptsTbody.addEventListener("click", (event) => this.handlePromptAction(event));
        this.promptForm.addEventListener("submit", (event) => {
            event.preventDefault();
            this.savePrompt();
        });
        this.promptTestBtn.addEventListener("click", () => this.testPromptPreview());

        document.getElementById("modelSearchBtn").addEventListener("click", () => {
            this.state.models.page = 1;
            this.loadModels();
        });
        document.getElementById("modelResetBtn").addEventListener("click", () => this.resetModels());
        document.getElementById("modelNewBtn").addEventListener("click", () => this.openModelEditor());
        this.modelsPrevBtn.addEventListener("click", () => this.changePage("models", -1));
        this.modelsNextBtn.addEventListener("click", () => this.changePage("models", 1));
        this.modelsTbody.addEventListener("click", (event) => this.handleModelAction(event));
        this.modelForm.addEventListener("submit", (event) => {
            event.preventDefault();
            this.saveModel();
        });
    }

    async init() {
        try {
            const me = await this.request("/api/admin/auth/me");
            this.currentAdmin = me.data.user;
            this.currentAdminNode.textContent = `${this.currentAdmin.nickname || this.currentAdmin.mobile}（${this.roleLabel(this.currentAdmin.role)}）`;
            this.activateView();
        } catch (error) {
            window.location.href = "/admin/login";
        }
    }

    resolveView() {
        if (window.location.pathname.includes("/admin/kb-files")) return "kb";
        if (window.location.pathname.includes("/admin/prompts")) return "prompts";
        if (window.location.pathname.includes("/admin/models")) return "models";
        return "users";
    }

    activateView() {
        const titles = {
            users: "用户管理",
            kb: "知识库文件管理",
            prompts: "系统提示词管理",
            models: "模型管理",
        };
        this.pageTitle.textContent = titles[this.view];
        Object.entries(this.views).forEach(([key, node]) => {
            node.hidden = key !== this.view;
        });
        document.querySelectorAll(".menu-link").forEach((link) => {
            link.classList.toggle("active", link.dataset.view === this.view);
        });
        if (this.view === "users") this.loadUsers();
        if (this.view === "kb") this.loadKbDocuments();
        if (this.view === "prompts") this.loadPrompts();
        if (this.view === "models") this.loadModels();
    }

    async request(url, options = {}) {
        const headers = options.body instanceof FormData ? {} : { "Content-Type": "application/json" };
        const response = await fetch(url, { credentials: "include", headers, ...options });
        const result = await response.json();
        if (!response.ok) throw new Error(result.message || "请求失败");
        return result;
    }

    async logout() {
        await this.request("/api/admin/auth/logout", { method: "POST" });
        window.location.href = "/admin/login";
    }

    changePage(key, delta) {
        const target = this.state[key];
        const next = target.page + delta;
        if (next < 1 || (target.totalPages && next > target.totalPages)) return;
        target.page = next;
        if (key === "users") this.loadUsers();
        if (key === "kb") this.loadKbDocuments();
        if (key === "prompts") this.loadPrompts();
        if (key === "models") this.loadModels();
    }

    async loadUsers() {
        const params = new URLSearchParams({
            page: String(this.state.users.page),
            page_size: String(this.state.users.pageSize),
        });
        if (this.mobileFilter.value.trim()) params.set("mobile", this.mobileFilter.value.trim());
        if (this.roleFilter.value) params.set("role", this.roleFilter.value);
        if (this.statusFilter.value) params.set("status", this.statusFilter.value);
        if (this.levelFilter.value) params.set("level", this.levelFilter.value);

        const result = await this.request(`/api/admin/users?${params.toString()}`);
        this.state.users.rows = result.data.list;
        this.state.users.totalPages = result.data.total_pages;
        this.renderUsers(result.data);
    }

    renderUsers(data) {
        this.usersTbody.innerHTML = "";
        this.usersEmpty.hidden = data.list.length > 0;
        data.list.forEach((user) => {
            const row = document.createElement("tr");
            row.innerHTML = `
                <td>${user.id}</td>
                <td>${this.escape(user.mobile)}</td>
                <td>${this.escape(user.nickname || "-")}</td>
                <td>${this.roleLabel(user.role)}</td>
                <td>${user.points}</td>
                <td>${this.levelBadge(user.membership_level)}</td>
                <td>${this.statusBadge(user.status === 1, "正常", "禁用")}</td>
                <td>${this.formatDate(user.last_login_at)}</td>
                <td>${this.formatDate(user.created_at)}</td>
                <td>
                    <div class="actions">
                        <button class="btn-text" data-action="detail" data-id="${user.id}">查看</button>
                        <button class="btn-text" data-action="edit" data-id="${user.id}">编辑</button>
                        <button class="btn-text" data-action="status" data-id="${user.id}">${user.status === 1 ? "禁用" : "启用"}</button>
                    </div>
                </td>
            `;
            this.usersTbody.appendChild(row);
        });
        this.usersPageMeta.textContent = `共 ${data.total} 条，第 ${data.page} / ${Math.max(data.total_pages, 1)} 页`;
        this.usersPrevBtn.disabled = data.page <= 1;
        this.usersNextBtn.disabled = !data.total_pages || data.page >= data.total_pages;
    }

    resetUsers() {
        this.mobileFilter.value = "";
        this.roleFilter.value = "";
        this.statusFilter.value = "";
        this.levelFilter.value = "";
        this.state.users.page = 1;
        this.loadUsers();
    }

    async handleUserAction(event) {
        const button = event.target.closest("[data-action]");
        if (!button) return;
        const userId = Number(button.dataset.id);
        if (button.dataset.action === "detail") return this.openUserDetail(userId);
        if (button.dataset.action === "edit") return this.openUserEditor(userId);
        if (button.dataset.action === "status") return this.toggleUserStatus(userId);
    }

    async openUserDetail(userId) {
        const result = await this.request(`/api/admin/users/${userId}`);
        const user = result.data;
        this.openDrawer("用户详情", `
            <div class="detail-list">
                ${this.detailRow("用户 ID", user.id)}
                ${this.detailRow("手机号", this.escape(user.mobile))}
                ${this.detailRow("昵称", this.escape(user.nickname || "-"))}
                ${this.detailRow("角色", this.roleLabel(user.role))}
                ${this.detailRow("状态", user.status === 1 ? "正常" : "禁用")}
                ${this.detailRow("积分", user.points)}
                ${this.detailRow("会员等级", this.escape(user.membership_level?.name || "-"))}
                ${this.detailRow("最近登录", this.formatDate(user.last_login_at))}
                ${this.detailRow("注册时间", this.formatDate(user.created_at))}
            </div>
        `);
    }

    async openUserEditor(userId) {
        const result = await this.request(`/api/admin/users/${userId}`);
        this.activeUser = result.data;
        this.userNickname.value = this.activeUser.nickname || "";
        this.userRole.value = this.activeUser.role;
        this.userStatus.value = String(this.activeUser.status);
        this.userRoleField.hidden = this.currentAdmin.role !== "super_admin";
        this.userMessage.textContent = "";
        this.userDialog.showModal();
    }

    async saveUser() {
        const payload = {
            nickname: this.userNickname.value.trim(),
            status: Number(this.userStatus.value),
        };
        if (this.currentAdmin.role === "super_admin") payload.role = this.userRole.value;
        try {
            await this.request(`/api/admin/users/${this.activeUser.id}`, {
                method: "PUT",
                body: JSON.stringify(payload),
            });
            this.userDialog.close();
            await this.loadUsers();
        } catch (error) {
            this.userMessage.textContent = error.message;
        }
    }

    async toggleUserStatus(userId) {
        const user = this.state.users.rows.find((item) => item.id === userId);
        if (!user) return;
        const enabled = user.status !== 1;
        if (!window.confirm(`确认${enabled ? "启用" : "禁用"}用户 ${user.mobile}？`)) return;
        await this.request(`/api/admin/users/${userId}/status`, {
            method: "PATCH",
            body: JSON.stringify({ status: enabled ? 1 : 0 }),
        });
        await this.loadUsers();
    }

    async uploadKbDocument() {
        this.kbUploadMessage.textContent = "";
        this.kbUploadMessage.classList.remove("success");
        const file = this.kbUploadFile.files[0];
        if (!file) {
            this.kbUploadMessage.textContent = "请选择 .md 或 .txt 文件";
            return;
        }
        const form = new FormData();
        form.append("file", file);
        form.append("category", this.kbUploadCategory.value.trim() || "default");
        form.append("description", this.kbUploadDescription.value.trim());
        try {
            this.kbUploadMessage.textContent = "正在上传并向量化，请稍候...";
            await this.request("/api/admin/kb/documents/upload", { method: "POST", body: form });
            this.kbUploadMessage.textContent = "上传成功";
            this.kbUploadMessage.classList.add("success");
            this.kbUploadForm.reset();
            this.kbUploadCategory.value = "default";
            this.state.kb.page = 1;
            await this.loadKbDocuments();
        } catch (error) {
            this.kbUploadMessage.textContent = error.message;
        }
    }

    async importExistingKbDocuments() {
        this.kbUploadMessage.textContent = "";
        this.kbUploadMessage.classList.remove("success");
        const shouldReindex = window.confirm("导入后是否立即重新向量化？取消则只登记文件和切片，之后可逐个重新向量化。");
        try {
            this.kbUploadMessage.textContent = shouldReindex
                ? "正在导入并重新向量化现有文件..."
                : "正在导入现有文件...";
            const result = await this.request(`/api/admin/kb/documents/import-existing?reindex=${shouldReindex}`, {
                method: "POST",
            });
            const data = result.data;
            this.kbUploadMessage.textContent =
                `导入 ${data.imported_count} 个，跳过 ${data.skipped_count} 个，失败 ${data.failed_count} 个，重新向量化 ${data.reindexed_count} 个`;
            this.kbUploadMessage.classList.add("success");
            this.state.kb.page = 1;
            await this.loadKbDocuments();
        } catch (error) {
            this.kbUploadMessage.textContent = error.message;
        }
    }

    async loadKbDocuments() {
        const params = new URLSearchParams({
            page: String(this.state.kb.page),
            page_size: String(this.state.kb.pageSize),
        });
        if (this.kbKeywordFilter.value.trim()) params.set("keyword", this.kbKeywordFilter.value.trim());
        if (this.kbCategoryFilter.value.trim()) params.set("category", this.kbCategoryFilter.value.trim());
        if (this.kbStatusFilter.value) params.set("vector_status", this.kbStatusFilter.value);
        if (this.kbEnabledFilter.value) params.set("enabled", this.kbEnabledFilter.value);
        const result = await this.request(`/api/admin/kb/documents?${params.toString()}`);
        this.state.kb.rows = result.data.list;
        this.state.kb.totalPages = result.data.total_pages;
        this.renderKbDocuments(result.data);
    }

    renderKbDocuments(data) {
        this.kbTbody.innerHTML = "";
        this.kbEmpty.hidden = data.list.length > 0;
        data.list.forEach((doc) => {
            const row = document.createElement("tr");
            row.innerHTML = `
                <td>${doc.id}</td>
                <td class="wide-cell">${this.escape(doc.original_file_name)}</td>
                <td>${this.escape(doc.file_type)}</td>
                <td>${this.escape(doc.category)}</td>
                <td>${doc.chunk_count}</td>
                <td>${this.vectorStatusBadge(doc.vector_status)}</td>
                <td>${this.statusBadge(doc.enabled, "启用", "停用")}</td>
                <td>${this.escape(doc.created_by?.nickname || doc.created_by?.mobile || "-")}</td>
                <td>${this.formatDate(doc.created_at)}</td>
                <td>${this.formatDate(doc.updated_at)}</td>
                <td>
                    <div class="actions">
                        <button class="btn-text" data-action="detail" data-id="${doc.id}">查看</button>
                        <button class="btn-text" data-action="edit" data-id="${doc.id}">编辑</button>
                        <button class="btn-text" data-action="content" data-id="${doc.id}">编辑文档</button>
                        <button class="btn-text" data-action="toggle" data-id="${doc.id}">${doc.enabled ? "停用" : "启用"}</button>
                        <button class="btn-text" data-action="reindex" data-id="${doc.id}">重新向量化</button>
                        <button class="btn-text" data-action="chunks" data-id="${doc.id}">切片</button>
                        <button class="btn-text danger-text" data-action="delete" data-id="${doc.id}">删除</button>
                    </div>
                </td>
            `;
            this.kbTbody.appendChild(row);
        });
        this.kbPageMeta.textContent = `共 ${data.total} 条，第 ${data.page} / ${Math.max(data.total_pages, 1)} 页`;
        this.kbPrevBtn.disabled = data.page <= 1;
        this.kbNextBtn.disabled = !data.total_pages || data.page >= data.total_pages;
    }

    resetKb() {
        this.kbKeywordFilter.value = "";
        this.kbCategoryFilter.value = "";
        this.kbStatusFilter.value = "";
        this.kbEnabledFilter.value = "";
        this.state.kb.page = 1;
        this.loadKbDocuments();
    }

    async handleKbAction(event) {
        const button = event.target.closest("[data-action]");
        if (!button) return;
        const id = Number(button.dataset.id);
        const action = button.dataset.action;
        if (action === "detail") return this.openKbDetail(id);
        if (action === "edit") return this.openKbEditor(id);
        if (action === "content") return this.openKbContentEditor(id);
        if (action === "toggle") return this.toggleKbEnabled(id);
        if (action === "reindex") return this.reindexKbDocument(id);
        if (action === "chunks") return this.openKbChunks(id);
        if (action === "delete") return this.deleteKbDocument(id);
    }

    async openKbDetail(id) {
        const result = await this.request(`/api/admin/kb/documents/${id}`);
        const doc = result.data;
        this.openDrawer("知识库文件详情", `
            <div class="detail-list">
                ${this.detailRow("文件 ID", doc.id)}
                ${this.detailRow("文件名", this.escape(doc.original_file_name))}
                ${this.detailRow("标题", this.escape(doc.title || "-"))}
                ${this.detailRow("分类", this.escape(doc.category))}
                ${this.detailRow("保存路径", this.escape(doc.file_path))}
                ${this.detailRow("文件大小", this.formatSize(doc.file_size))}
                ${this.detailRow("切片数量", doc.chunk_count)}
                ${this.detailRow("向量状态", doc.vector_status)}
                ${this.detailRow("是否启用", doc.enabled ? "启用" : "停用")}
                ${this.detailRow("错误信息", this.escape(doc.error_message || "-"))}
            </div>
        `);
    }

    async openKbEditor(id) {
        const result = await this.request(`/api/admin/kb/documents/${id}`);
        this.activeDocument = result.data;
        this.kbEditTitle.value = this.activeDocument.title || "";
        this.kbEditCategory.value = this.activeDocument.category || "default";
        this.kbEditDescription.value = this.activeDocument.description || "";
        this.kbEditMessage.textContent = "";
        this.kbDialog.showModal();
    }

    async saveKbDocument() {
        try {
            await this.request(`/api/admin/kb/documents/${this.activeDocument.id}`, {
                method: "PUT",
                body: JSON.stringify({
                    title: this.kbEditTitle.value.trim(),
                    category: this.kbEditCategory.value.trim() || "default",
                    description: this.kbEditDescription.value.trim(),
                }),
            });
            this.kbDialog.close();
            await this.loadKbDocuments();
        } catch (error) {
            this.kbEditMessage.textContent = error.message;
        }
    }

    async openKbContentEditor(id) {
        const result = await this.request(`/api/admin/kb/documents/${id}/content`);
        this.activeDocument = result.data.document;
        this.kbContentTitle.textContent = `编辑切片文档：${this.activeDocument.original_file_name}`;
        this.kbContentEditor.value = result.data.content || "";
        this.kbContentReindex.checked = false;
        this.kbContentMessage.textContent = "";
        this.kbContentMessage.classList.remove("success");
        this.kbContentDialog.showModal();
    }

    async saveKbContent() {
        if (!this.activeDocument) return;
        this.kbContentMessage.textContent = this.kbContentReindex.checked
            ? "正在保存并重新向量化..."
            : "正在保存并刷新切片...";
        this.kbContentMessage.classList.remove("success");
        try {
            await this.request(`/api/admin/kb/documents/${this.activeDocument.id}/content`, {
                method: "PUT",
                body: JSON.stringify({
                    content: this.kbContentEditor.value,
                    reindex: this.kbContentReindex.checked,
                }),
            });
            this.kbContentMessage.textContent = this.kbContentReindex.checked
                ? "保存成功，已重新向量化"
                : "保存成功，已刷新切片，等待重新向量化";
            this.kbContentMessage.classList.add("success");
            await this.loadKbDocuments();
        } catch (error) {
            this.kbContentMessage.textContent = error.message;
        }
    }

    async toggleKbEnabled(id) {
        const doc = this.state.kb.rows.find((item) => item.id === id);
        if (!doc) return;
        const next = !doc.enabled;
        await this.request(`/api/admin/kb/documents/${id}/enabled`, {
            method: "PATCH",
            body: JSON.stringify({ enabled: next }),
        });
        await this.loadKbDocuments();
    }

    async reindexKbDocument(id) {
        if (!window.confirm("确认重新向量化这个文件？")) return;
        await this.request(`/api/admin/kb/documents/${id}/reindex`, { method: "POST" });
        await this.loadKbDocuments();
    }

    async deleteKbDocument(id) {
        if (!window.confirm("确认删除这个知识库文件？删除后将不参与检索。")) return;
        await this.request(`/api/admin/kb/documents/${id}`, { method: "DELETE" });
        await this.loadKbDocuments();
    }

    async openKbChunks(id) {
        const result = await this.request(`/api/admin/kb/documents/${id}/chunks?page=1&page_size=50`);
        const html = result.data.list.length
            ? `<div class="chunk-list">${result.data.list.map((chunk) => `
                <article class="chunk-card">
                    <strong>#${chunk.chunk_index}</strong>
                    <p>${this.escape(chunk.content)}</p>
                </article>
            `).join("")}</div>`
            : `<div class="empty">暂无切片</div>`;
        this.openDrawer("文件切片", html);
    }

    async runKbSearchTest() {
        this.kbSearchResults.innerHTML = "";
        const query = this.kbSearchQuery.value.trim();
        if (!query) return;
        const result = await this.request("/api/admin/kb/search-test", {
            method: "POST",
            body: JSON.stringify({
                query,
                top_k: Number(this.kbSearchTopK.value || 5),
                category: this.kbSearchCategory.value.trim() || null,
            }),
        });
        const rows = result.data.results || [];
        this.kbSearchResults.innerHTML = rows.length
            ? rows.map((item) => `
                <article class="result-card">
                    <div class="result-title">
                        <strong>${this.escape(item.file_name)} / #${item.chunk_index}</strong>
                        <span>score: ${Number(item.score).toFixed(4)}</span>
                    </div>
                    <p>${this.escape(item.content)}</p>
                </article>
            `).join("")
            : `<div class="empty">没有检索到结果</div>`;
    }

    async loadPrompts() {
        const params = new URLSearchParams({
            page: String(this.state.prompts.page),
            page_size: String(this.state.prompts.pageSize),
        });
        if (this.promptKeywordFilter.value.trim()) params.set("keyword", this.promptKeywordFilter.value.trim());
        if (this.promptTypeFilter.value.trim()) params.set("prompt_type", this.promptTypeFilter.value.trim());
        if (this.promptEnabledFilter.value) params.set("enabled", this.promptEnabledFilter.value);
        const result = await this.request(`/api/admin/prompts?${params.toString()}`);
        this.state.prompts.rows = result.data.list;
        this.state.prompts.totalPages = result.data.total_pages;
        this.renderPrompts(result.data);
    }

    renderPrompts(data) {
        this.promptsTbody.innerHTML = "";
        this.promptsEmpty.hidden = data.list.length > 0;
        data.list.forEach((prompt) => {
            const row = document.createElement("tr");
            row.innerHTML = `
                <td>${prompt.id}</td>
                <td>${this.escape(prompt.prompt_name)}</td>
                <td>${this.escape(prompt.prompt_key)}</td>
                <td>${this.escape(prompt.prompt_type)}</td>
                <td>v${prompt.version}</td>
                <td>${this.statusBadge(prompt.enabled, "启用中", "未启用")}</td>
                <td>${this.escape(prompt.updated_by?.nickname || prompt.updated_by?.mobile || "-")}</td>
                <td>${this.formatDate(prompt.updated_at)}</td>
                <td>
                    <div class="actions">
                        <button class="btn-text" data-action="detail" data-id="${prompt.id}">查看</button>
                        <button class="btn-text" data-action="edit" data-id="${prompt.id}">编辑</button>
                        <button class="btn-text" data-action="copy" data-id="${prompt.id}">复制新版本</button>
                        <button class="btn-text" data-action="enable" data-id="${prompt.id}">${prompt.enabled ? "停用" : "启用"}</button>
                        <button class="btn-text" data-action="versions" data-key="${this.escape(prompt.prompt_key)}">历史版本</button>
                    </div>
                </td>
            `;
            this.promptsTbody.appendChild(row);
        });
        this.promptsPageMeta.textContent = `共 ${data.total} 条，第 ${data.page} / ${Math.max(data.total_pages, 1)} 页`;
        this.promptsPrevBtn.disabled = data.page <= 1;
        this.promptsNextBtn.disabled = !data.total_pages || data.page >= data.total_pages;
    }

    resetPrompts() {
        this.promptKeywordFilter.value = "";
        this.promptTypeFilter.value = "";
        this.promptEnabledFilter.value = "";
        this.state.prompts.page = 1;
        this.loadPrompts();
    }

    async handlePromptAction(event) {
        const button = event.target.closest("[data-action]");
        if (!button) return;
        const action = button.dataset.action;
        const id = Number(button.dataset.id);
        if (action === "detail") return this.openPromptDetail(id);
        if (action === "edit") return this.openPromptEditor(id);
        if (action === "copy") return this.copyPrompt(id);
        if (action === "enable") return this.togglePromptEnabled(id);
        if (action === "versions") return this.openPromptVersions(button.dataset.key);
    }

    openPromptEditor(id = null) {
        this.activePrompt = null;
        this.promptDialogTitle.textContent = id ? "编辑提示词" : "新增提示词";
        this.promptKey.disabled = Boolean(id);
        this.promptEnableOnCreateField.hidden = Boolean(id);
        this.promptTestOutput.textContent = "";
        this.promptMessage.textContent = "";
        if (!id) {
            this.promptKey.value = "";
            this.promptName.value = "";
            this.promptType.value = "";
            this.promptContent.value = "";
            this.promptRemark.value = "";
            this.promptEnableOnCreate.checked = false;
            this.promptDialog.showModal();
            return;
        }
        this.request(`/api/admin/prompts/${id}`).then((result) => {
            this.activePrompt = result.data;
            this.promptKey.value = this.activePrompt.prompt_key;
            this.promptName.value = this.activePrompt.prompt_name;
            this.promptType.value = this.activePrompt.prompt_type;
            this.promptContent.value = this.activePrompt.content;
            this.promptRemark.value = this.activePrompt.remark || "";
            this.promptDialog.showModal();
        });
    }

    async savePrompt() {
        const payload = {
            prompt_name: this.promptName.value.trim(),
            prompt_type: this.promptType.value.trim(),
            content: this.promptContent.value.trim(),
            remark: this.promptRemark.value.trim(),
        };
        if (!payload.prompt_name || !payload.prompt_type || !payload.content) {
            this.promptMessage.textContent = "请填写名称、类型和内容";
            return;
        }
        try {
            if (this.activePrompt) {
                await this.request(`/api/admin/prompts/${this.activePrompt.id}`, {
                    method: "PUT",
                    body: JSON.stringify(payload),
                });
            } else {
                await this.request("/api/admin/prompts", {
                    method: "POST",
                    body: JSON.stringify({
                        prompt_key: this.promptKey.value.trim(),
                        ...payload,
                        enabled: this.promptEnableOnCreate.checked,
                    }),
                });
            }
            this.promptDialog.close();
            await this.loadPrompts();
        } catch (error) {
            this.promptMessage.textContent = error.message;
        }
    }

    async openPromptDetail(id) {
        const result = await this.request(`/api/admin/prompts/${id}`);
        const prompt = result.data;
        this.openDrawer("提示词详情", `
            <div class="detail-list">
                ${this.detailRow("名称", this.escape(prompt.prompt_name))}
                ${this.detailRow("编码", this.escape(prompt.prompt_key))}
                ${this.detailRow("类型", this.escape(prompt.prompt_type))}
                ${this.detailRow("版本", `v${prompt.version}`)}
                ${this.detailRow("状态", prompt.enabled ? "启用中" : "未启用")}
            </div>
            <pre class="code-preview">${this.escape(prompt.content)}</pre>
        `);
    }

    async copyPrompt(id) {
        await this.request(`/api/admin/prompts/${id}/copy`, { method: "POST" });
        await this.loadPrompts();
    }

    async togglePromptEnabled(id) {
        const prompt = this.state.prompts.rows.find((item) => item.id === id);
        if (!prompt) return;
        if (prompt.enabled) {
            if (!window.confirm("确认停用这个提示词版本？")) return;
            await this.request(`/api/admin/prompts/${id}/disable`, { method: "PATCH" });
        } else {
            if (!window.confirm("确认启用这个版本？同编码的其他版本会自动停用。")) return;
            await this.request(`/api/admin/prompts/${id}/enable`, { method: "PATCH" });
        }
        await this.loadPrompts();
    }

    async openPromptVersions(promptKey) {
        const result = await this.request(`/api/admin/prompts/key/${encodeURIComponent(promptKey)}/versions`);
        const html = result.data.list.length
            ? `<div class="log-list">${result.data.list.map((item) => `
                <article class="log-item">
                    <div class="log-title">
                        <strong>v${item.version} ${this.escape(item.prompt_name)}</strong>
                        <span>${item.enabled ? "启用中" : "未启用"}</span>
                    </div>
                    <p>${this.escape(item.prompt_type)} / ${this.formatDate(item.updated_at)}</p>
                </article>
            `).join("")}</div>`
            : `<div class="empty">暂无历史版本</div>`;
        this.openDrawer("历史版本", html);
    }

    async testPromptPreview() {
        const key = this.promptKey.value.trim();
        const input = this.promptTestInput.value.trim();
        if (!key || !input) {
            this.promptTestOutput.textContent = "请填写提示词编码和测试输入";
            return;
        }
        try {
            const result = await this.request("/api/admin/prompts/test", {
                method: "POST",
                body: JSON.stringify({ prompt_key: key, test_input: input }),
            });
            this.promptTestOutput.textContent = result.data.preview;
        } catch (error) {
            this.promptTestOutput.textContent = error.message;
        }
    }

    async loadModels() {
        const params = new URLSearchParams({
            page: String(this.state.models.page),
            page_size: String(this.state.models.pageSize),
        });
        if (this.modelKeywordFilter.value.trim()) params.set("keyword", this.modelKeywordFilter.value.trim());
        if (this.modelEnabledFilter.value) params.set("enabled", this.modelEnabledFilter.value);
        const result = await this.request(`/api/admin/model-catalog?${params.toString()}`);
        this.state.models.rows = result.data.list;
        this.state.models.totalPages = result.data.total_pages;
        this.renderModels(result.data);
    }

    renderModels(data) {
        this.modelsTbody.innerHTML = "";
        this.modelsEmpty.hidden = data.list.length > 0;
        data.list.forEach((model) => {
            const usage = model.usage || {};
            const row = document.createElement("tr");
            row.innerHTML = `
                <td>
                    <strong>${this.escape(model.displayName)}</strong>
                    ${model.isDefault ? `<span class="badge badge-success">默认</span>` : ""}
                </td>
                <td>
                    <strong>${this.escape(model.modelId)}</strong>
                    <div class="muted">${this.escape(model.provider || "dashscope")}</div>
                </td>
                <td>${this.statusBadge(model.enabled, "启用中", "已停用")}</td>
                <td>${usage.today || 0}</td>
                <td>${usage.month || 0}</td>
                <td>${usage.total || 0}</td>
                <td>${usage.failureTotal || 0}</td>
                <td>${this.formatDate(usage.lastUsedAt)}</td>
                <td>
                    <div class="actions">
                        <button class="btn-text" data-action="usage" data-id="${model.id}">用量</button>
                        <button class="btn-text" data-action="edit" data-id="${model.id}">编辑</button>
                        ${model.isDefault ? "" : `<button class="btn-text" data-action="default" data-id="${model.id}">设默认</button>`}
                        <button class="btn-text" data-action="enable" data-id="${model.id}">${model.enabled ? "停用" : "启用"}</button>
                        ${model.isDefault ? "" : `<button class="btn-text danger" data-action="delete" data-id="${model.id}">删除</button>`}
                    </div>
                </td>
            `;
            this.modelsTbody.appendChild(row);
        });
        this.modelsPageMeta.textContent = `共 ${data.total} 条，第 ${data.page} / ${Math.max(data.total_pages, 1)} 页`;
        this.modelsPrevBtn.disabled = data.page <= 1;
        this.modelsNextBtn.disabled = !data.total_pages || data.page >= data.total_pages;
    }

    resetModels() {
        this.modelKeywordFilter.value = "";
        this.modelEnabledFilter.value = "";
        this.state.models.page = 1;
        this.loadModels();
    }

    async handleModelAction(event) {
        const button = event.target.closest("[data-action]");
        if (!button) return;
        const action = button.dataset.action;
        const id = Number(button.dataset.id);
        if (action === "usage") return this.openModelUsage(id);
        if (action === "edit") return this.openModelEditor(id);
        if (action === "default") return this.setDefaultModel(id);
        if (action === "enable") return this.toggleModelEnabled(id);
        if (action === "delete") return this.deleteModel(id);
    }

    openModelEditor(id = null) {
        this.activeModel = null;
        this.modelDialogTitle.textContent = id ? "编辑模型" : "新增模型";
        this.modelMessage.textContent = "";
        if (!id) {
            this.modelDisplayName.value = "";
            this.modelId.value = "";
            this.modelProvider.value = "dashscope";
            this.modelSortOrder.value = "100";
            this.modelEnabled.checked = true;
            this.modelDefault.checked = false;
            this.modelRemark.value = "";
            this.modelDialog.showModal();
            return;
        }
        this.request(`/api/admin/model-catalog/${id}`).then((result) => {
            this.activeModel = result.data;
            this.modelDisplayName.value = this.activeModel.displayName;
            this.modelId.value = this.activeModel.modelId;
            this.modelProvider.value = this.activeModel.provider;
            this.modelSortOrder.value = String(this.activeModel.sortOrder || 100);
            this.modelEnabled.checked = Boolean(this.activeModel.enabled);
            this.modelDefault.checked = Boolean(this.activeModel.isDefault);
            this.modelRemark.value = this.activeModel.remark || "";
            this.modelDialog.showModal();
        });
    }

    async saveModel() {
        const payload = {
            display_name: this.modelDisplayName.value.trim(),
            model_id: this.modelId.value.trim(),
            provider: this.modelProvider.value.trim() || "dashscope",
            enabled: this.modelEnabled.checked,
            is_default: this.modelDefault.checked,
            sort_order: Number(this.modelSortOrder.value || 100),
            remark: this.modelRemark.value.trim(),
        };
        if (!payload.display_name || !payload.model_id) {
            this.modelMessage.textContent = "请填写模型名称和模型 ID";
            return;
        }
        try {
            if (this.activeModel) {
                await this.request(`/api/admin/model-catalog/${this.activeModel.id}`, {
                    method: "PUT",
                    body: JSON.stringify(payload),
                });
            } else {
                await this.request("/api/admin/model-catalog", {
                    method: "POST",
                    body: JSON.stringify(payload),
                });
            }
            this.modelDialog.close();
            await this.loadModels();
        } catch (error) {
            this.modelMessage.textContent = error.message;
        }
    }

    async toggleModelEnabled(id) {
        const model = this.state.models.rows.find((item) => item.id === id);
        if (!model) return;
        const nextEnabled = !model.enabled;
        if (!window.confirm(`确认${nextEnabled ? "启用" : "停用"}模型 ${model.provider || "dashscope"} / ${model.modelId}？`)) return;
        await this.request(`/api/admin/model-catalog/${id}/enabled`, {
            method: "PATCH",
            body: JSON.stringify({ enabled: nextEnabled }),
        });
        await this.loadModels();
    }

    async setDefaultModel(id) {
        const model = this.state.models.rows.find((item) => item.id === id);
        if (!model) return;
        if (!window.confirm(`确认将 ${model.provider || "dashscope"} / ${model.modelId} 设为默认模型？`)) return;
        await this.request(`/api/admin/model-catalog/${id}/default`, { method: "PATCH" });
        await this.loadModels();
    }

    async deleteModel(id) {
        const model = this.state.models.rows.find((item) => item.id === id);
        if (!model) return;
        if (!window.confirm(`确认删除模型 ${model.provider || "dashscope"} / ${model.modelId}？历史用量统计会保留。`)) return;
        await this.request(`/api/admin/model-catalog/${id}`, { method: "DELETE" });
        await this.loadModels();
    }

    async openModelUsage(id) {
        const result = await this.request(`/api/admin/model-catalog/${id}/usage?days=30`);
        const data = result.data;
        const summary = data.summary || {};
        const topUsers = data.topUsers || [];
        const topUsersHtml = topUsers.length
            ? `<div class="log-list">${topUsers.map((item) => `
                <article class="log-item">
                    <div class="log-title">
                        <strong>${this.escape(item.nickname || item.mobile || "未知用户")}</strong>
                        <span>${item.usageTotal} 次</span>
                    </div>
                    <p>最近使用：${this.formatDate(item.lastUsedAt)}</p>
                </article>
            `).join("")}</div>`
            : `<div class="empty">近 30 天暂无用户使用记录</div>`;
        this.openDrawer("模型用量", `
            <div class="detail-list">
                ${this.detailRow("模型", `${this.escape(data.model.provider || "dashscope")} / ${this.escape(data.model.displayName)} / ${this.escape(data.model.modelId)}`)}
                ${this.detailRow("近 30 天调用", summary.total || 0)}
                ${this.detailRow("成功", summary.successTotal || 0)}
                ${this.detailRow("失败", summary.failureTotal || 0)}
                ${this.detailRow("平均耗时", summary.avgDurationMs ? `${summary.avgDurationMs} ms` : "-")}
                ${this.detailRow("最近使用", this.formatDate(summary.lastUsedAt))}
            </div>
            <h4 class="drawer-section-title">使用最多的用户</h4>
            ${topUsersHtml}
        `);
    }

    openDrawer(title, html) {
        this.drawerTitle.textContent = title;
        this.drawerBody.innerHTML = html;
        this.sideDrawer.classList.add("open");
        this.drawerMask.classList.add("open");
    }

    closeDrawer() {
        this.sideDrawer.classList.remove("open");
        this.drawerMask.classList.remove("open");
    }

    detailRow(label, value) {
        return `<div class="detail-row"><span>${label}</span><strong>${value}</strong></div>`;
    }

    roleLabel(role) {
        return { user: "普通用户", admin: "管理员", super_admin: "超级管理员" }[role] || role;
    }

    levelBadge(level) {
        if (!level) return "-";
        return `<span class="badge badge-${level.code}">${this.escape(level.name)}</span>`;
    }

    statusBadge(active, activeLabel, inactiveLabel) {
        return active
            ? `<span class="badge badge-success">${activeLabel}</span>`
            : `<span class="badge badge-muted">${inactiveLabel}</span>`;
    }

    vectorStatusBadge(status) {
        const labels = { pending: "待处理", processing: "向量化中", success: "已入库", failed: "失败" };
        const badgeClass = status === "success" ? "badge-success" : status === "failed" ? "badge-danger" : "badge-muted";
        return `<span class="badge ${badgeClass}">${labels[status] || status}</span>`;
    }

    formatDate(value) {
        if (!value) return "-";
        return new Date(value).toLocaleString("zh-CN", { hour12: false });
    }

    formatSize(value) {
        const size = Number(value || 0);
        if (size < 1024) return `${size} B`;
        if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
        return `${(size / 1024 / 1024).toFixed(1)} MB`;
    }

    escape(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }
}

document.addEventListener("DOMContentLoaded", () => {
    new AdminApp();
});
