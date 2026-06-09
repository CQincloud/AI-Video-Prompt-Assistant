class LoginPage {
    constructor() {
        this.form = document.getElementById("loginForm");
        this.phoneInput = document.getElementById("phoneInput");
        this.codeInput = document.getElementById("codeInput");
        this.sendCodeBtn = document.getElementById("sendCodeBtn");
        this.loginBtn = document.getElementById("loginBtn");
        this.message = document.getElementById("authMessage");
        this.codeLength = 6;
        this.countdown = 0;
        this.timer = null;

        this.bindEvents();
        this.redirectIfLoggedIn();
    }

    bindEvents() {
        this.sendCodeBtn.addEventListener("click", () => this.sendCode());
        this.form.addEventListener("submit", (event) => {
            event.preventDefault();
            this.login();
        });

        this.phoneInput.addEventListener("input", () => {
            this.phoneInput.value = this.phoneInput.value.replace(/\D/g, "").slice(0, 11);
        });
        this.codeInput.addEventListener("input", () => {
            this.codeInput.value = this.codeInput.value.replace(/\D/g, "").slice(0, this.codeLength);
        });
    }

    async redirectIfLoggedIn() {
        try {
            const response = await fetch("/api/auth/me", { credentials: "include" });
            if (response.ok) {
                window.location.href = this.getRedirectPath();
            }
        } catch (error) {
            console.debug("Auth status check skipped", error);
        }
    }

    async sendCode() {
        const phone = this.getPhone();
        if (!phone) return;

        this.setMessage("");
        this.sendCodeBtn.disabled = true;
        this.sendCodeBtn.textContent = "发送中...";

        try {
            const response = await fetch("/api/auth/send-code", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "include",
                body: JSON.stringify({ phone }),
            });
            const result = await this.readJsonResponse(response);
            if (!response.ok) {
                throw new Error(result.message || "验证码发送失败");
            }

            const debugCode = result.data && result.data.debug_code ? ` 当前 mock 验证码：${result.data.debug_code}` : "";
            this.codeInput.value = "";
            this.codeInput.focus();
            this.setMessage(`验证码已发送，请查收短信。${debugCode}`, "success");
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
        this.loginBtn.textContent = "正在进入...";
        this.setMessage("");

        try {
            const response = await fetch("/api/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "include",
                body: JSON.stringify({ phone, code }),
            });
            const result = await this.readJsonResponse(response);
            if (!response.ok) {
                throw new Error(result.message || "登录失败");
            }

            this.setMessage("登录成功，正在进入助手。", "success");
            await this.waitForSessionReady();
            window.location.replace(this.getRedirectPath());
        } catch (error) {
            this.setMessage(error.message || "登录失败，请稍后再试");
            this.loginBtn.disabled = false;
            this.loginBtn.textContent = "立即进入";
        }
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

    async waitForSessionReady() {
        for (const delay of [300, 700, 1200, 1800]) {
            await this.sleep(delay);
            try {
                const response = await fetch("/api/auth/me", {
                    credentials: "include",
                    cache: "no-store",
                });
                if (response.ok) return true;
            } catch (error) {
                console.debug("Auth cookie check retry", error);
            }
        }
        console.debug("Auth cookie check did not pass before redirect; continuing navigation");
        return false;
    }

    sleep(milliseconds) {
        return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
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
        this.sendCodeBtn.textContent = `${this.countdown}s 后重新获取`;
    }

    setMessage(text, type = "error") {
        this.message.textContent = text;
        this.message.classList.toggle("success", type === "success");
    }

    getRedirectPath() {
        const params = new URLSearchParams(window.location.search);
        const redirect = params.get("redirect") || "/";
        if (!redirect.startsWith("/") || redirect.startsWith("//") || redirect.startsWith("/login")) {
            return "/";
        }
        return redirect;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    new LoginPage();
});
