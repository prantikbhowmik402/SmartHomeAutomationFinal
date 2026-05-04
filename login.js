/* ═══════════════════════════════════════════════════════
   login.js — Fixed version
   Fixes: active-tab class toggling on Login/Signup buttons
   ═══════════════════════════════════════════════════════ */

function showLogin() {
  document.getElementById("loginForm").style.display = "block";
  document.getElementById("signupForm").style.display = "none";
  const btns = document.querySelectorAll("#form-toggle button");
  btns[0].classList.add("active-tab");
  btns[1].classList.remove("active-tab");
}

function showSignup() {
  document.getElementById("loginForm").style.display = "none";
  document.getElementById("signupForm").style.display = "block";
  const btns = document.querySelectorAll("#form-toggle button");
  btns[1].classList.add("active-tab");
  btns[0].classList.remove("active-tab");
}

document.addEventListener("DOMContentLoaded", function () {

  // Show login tab as active by default on page load
  showLogin();

  // ── LOGIN ──────────────────────────────────────────────
  document.getElementById("loginForm").addEventListener("submit", function (e) {
    e.preventDefault();

    const email    = document.getElementById("loginEmail").value.trim();
    const password = document.getElementById("loginPassword").value;

    if (!email || !password) {
      alert("Please enter both email and password.");
      return;
    }

    const submitBtn = this.querySelector("button[type='submit']");
    submitBtn.disabled = true;
    submitBtn.textContent = "Logging in...";

    fetch("/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.success) {
          window.location.href = "/";
        } else {
          alert(data.message || "Login failed. Please check your credentials.");
          submitBtn.disabled = false;
          submitBtn.textContent = "Login";
        }
      })
      .catch((err) => {
        console.error("Login error:", err);
        alert("Something went wrong. Please try again.");
        submitBtn.disabled = false;
        submitBtn.textContent = "Login";
      });
  });

  // ── SIGNUP ─────────────────────────────────────────────
  document.getElementById("signupForm").addEventListener("submit", function (e) {
    e.preventDefault();

    const name     = document.getElementById("signupName").value.trim();
    const email    = document.getElementById("signupEmail").value.trim();
    const password = document.getElementById("signupPassword").value;

    if (!name || !email || !password) {
      alert("Please fill in all fields.");
      return;
    }

    if (password.length < 6) {
      alert("Password must be at least 6 characters.");
      return;
    }

    const submitBtn = this.querySelector("button[type='submit']");
    submitBtn.disabled = true;
    submitBtn.textContent = "Signing up...";

    fetch("/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, email, password }),
    })
      .then((res) => res.json())
      .then((data) => {
        alert(data.message);
        if (data.success) {
          // Clear signup form fields
          document.getElementById("signupName").value     = "";
          document.getElementById("signupEmail").value    = "";
          document.getElementById("signupPassword").value = "";

          // Switch to login tab and pre-fill email
          showLogin();
          document.getElementById("loginEmail").value = email;
        }
        submitBtn.disabled = false;
        submitBtn.textContent = "Signup";
      })
      .catch((err) => {
        console.error("Signup error:", err);
        alert("Something went wrong. Please try again.");
        submitBtn.disabled = false;
        submitBtn.textContent = "Signup";
      });
  });

});
