class AdminLoginPage {
    constructor() {
        this.form = document.getElementById("adminLoginForm");
        this.phoneInput = document.getElementById("phoneInput");
        this.codeInput = document.getElementById("codeInput");
        this.sendCodeBtn = document.getElementById("sendCodeBtn");
        this.loginBtn = document.getElementById("loginBtn");
        this.message = document.getElementById("loginMessage");
        this.codeLength = 6;
        this.countdown = 0;
        this.timer = null;

        this.bindEvents();
        this.redirectIfLoggedIn();
    }

    bindEvents() {
        this.phoneInput.addEventListener("input", () => {
            this.phoneInput.value = this.phoneInput.value.replace(/\D/g, "").slice(0, 11);
        });
        this.codeInput.addEventListener("input", () => {
            this.codeInput.value = this.codeInput.value.replace(/\D/g, "").slice(0, this.codeLength);
        });
        this.sendCodeBtn.addEventListener("click", () => this.sendCode());
        this.form.addEventListener("submit", (event) => {
            event.preventDefault();
            this.login();
        });
    }

    async redirectIfLoggedIn() {
        try {
            const response = await fetch("/api/admin/auth/me", { credentials: "include" });
            if (response.ok) {
                window.location.href = "/admin/users";
            }
        } catch (error) {
            console.debug("Admin auth status check skipped", error);
        }
    }

    async sendCode() {
        const phone = this.getPhone();
        if (!phone) return;

        this.setMessage("");
        this.sendCodeBtn.disabled = true;
        this.sendCodeBtn.textContent = "发送中...";

        try {
            const result = await this.request("/api/admin/auth/send-code", {
                method: "POST",
                body: JSON.stringify({ phone }),
            });
            const debugCode = result.data?.debug_code ? ` 当前调试验证码：${result.data.debug_code}` : "";
            this.codeInput.value = "";
            this.codeInput.focus();
            this.setMessage(`验证码已发送。${debugCode}`, "success");
            this.startCountdown(59);
        } catch (error) {
            this.setMessage(error.message || "验证码发送失败");
            this.sendCodeBtn.disabled = false;
            this.sendCodeBtn.textContent = "重新获取";
        }
    }

    async login() {
        const phone = this.getPhone();
        if (!phone) return;

        const code = this.codeInput.value.trim();
        const codePattern = new RegExp(`^\\d{${this.codeLength}}$`);
        if (!codePattern.test(code)) {
            this.setMessage(`请输入 ${this.codeLength} 位短信验证码`);
            this.codeInput.focus();
            return;
        }

        this.loginBtn.disabled = true;
        this.loginBtn.textContent = "登录中...";
        this.setMessage("");

        try {
            const result = await this.request("/api/admin/auth/login", {
                method: "POST",
                body: JSON.stringify({ phone, code }),
            });
            const redirect = result.data?.redirect || "/admin/users";
            const isAdminRedirect = redirect.startsWith("/admin/");
            this.setMessage(isAdminRedirect ? "登录成功，正在进入后台。" : "已登录普通账号，正在返回 AI 助手。", "success");
            window.location.href = redirect;
        } catch (error) {
            this.setMessage(error.message || "登录失败");
            this.loginBtn.disabled = false;
            this.loginBtn.textContent = "登录后台";
        }
    }

    async request(url, options = {}) {
        const response = await fetch(url, {
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            ...options,
        });
        const result = await this.readJsonResponse(response);
        if (!response.ok) {
            throw new Error(result.message || "请求失败");
        }
        return result;
    }

    async readJsonResponse(response) {
        const text = await response.text();
        try {
            return text ? JSON.parse(text) : {};
        } catch (error) {
            return {
                code: response.status || 500,
                message: response.ok ? "响应解析失败" : "服务暂时不可用，请稍后再试",
                data: null,
            };
        }
    }

    getPhone() {
        const phone = this.phoneInput.value.trim();
        if (!/^1[3-9]\d{9}$/.test(phone)) {
            this.setMessage("请输入正确的手机号");
            this.phoneInput.focus();
            return "";
        }
        return phone;
    }

    startCountdown(seconds) {
        this.countdown = seconds;
        window.clearInterval(this.timer);
        this.updateCountdown();
        this.timer = window.setInterval(() => {
            this.countdown -= 1;
            if (this.countdown <= 0) {
                window.clearInterval(this.timer);
                this.sendCodeBtn.disabled = false;
                this.sendCodeBtn.textContent = "重新获取";
                return;
            }
            this.updateCountdown();
        }, 1000);
    }

    updateCountdown() {
        this.sendCodeBtn.textContent = `${this.countdown}s 后重发`;
    }

    setMessage(text, type = "error") {
        this.message.textContent = text;
        this.message.classList.toggle("success", type === "success");
    }
}

document.addEventListener("DOMContentLoaded", () => {
    new AdminLoginPage();
});
