// Frontend logic for the Spotify Playlist Creator web app.

const loginView = document.getElementById("login-view");
const appView = document.getElementById("app-view");
const userName = document.getElementById("user-name");
const form = document.getElementById("playlist-form");
const submitBtn = document.getElementById("submit-btn");
const result = document.getElementById("result");

// Check whether the user is already logged in, and show the right view.
async function checkAuth() {
  try {
    const res = await fetch("/api/me");
    const data = await res.json();
    if (data.logged_in) {
      userName.textContent = data.display_name;
      appView.classList.remove("hidden");
      loginView.classList.add("hidden");
    } else {
      loginView.classList.remove("hidden");
      appView.classList.add("hidden");
    }
  } catch (err) {
    loginView.classList.remove("hidden");
  }
}

function showResult(html, type) {
  result.innerHTML = html;
  result.className = "card result " + type;
  result.classList.remove("hidden");
  result.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();

  const payload = {
    name: document.getElementById("name").value,
    description: document.getElementById("description").value,
    public: document.getElementById("public").checked,
    songs: document.getElementById("songs").value,
    seed_artists: document.getElementById("seed_artists").value,
    seed_genres: document.getElementById("seed_genres").value,
    seed_tracks: document.getElementById("seed_tracks").value,
    count: document.getElementById("count").value,
  };

  submitBtn.disabled = true;
  submitBtn.textContent = "Creating...";
  result.classList.add("hidden");

  try {
    const res = await fetch("/api/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (res.ok && data.ok) {
      let html = `✅ <strong>Created "${data.name}"</strong> with ${data.added} track(s).<br />`;
      html += `<a href="${data.url}" target="_blank" rel="noopener">Open in Spotify →</a>`;
      if (data.not_found && data.not_found.length) {
        html += `<p class="muted">Couldn't find: ${data.not_found
          .map((s) => escapeHtml(s))
          .join(", ")}</p>`;
      }
      showResult(html, "success");
    } else {
      showResult("⚠️ " + escapeHtml(data.error || "Something went wrong."), "error");
    }
  } catch (err) {
    showResult("⚠️ Network error: " + escapeHtml(err.message), "error");
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Create playlist";
  }
});

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

checkAuth();
