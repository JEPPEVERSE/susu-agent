const elements = {
  messages: document.querySelector("#messages"),
  composer: document.querySelector("#composer"),
  question: document.querySelector("#question"),
  send: document.querySelector("#send-button"),
  newChat: document.querySelector("#new-chat"),
  sessionList: document.querySelector("#session-list"),
  sessionId: document.querySelector("#session-id"),
  planVersion: document.querySelector("#plan-version"),
  strategyNode: document.querySelector("#strategy-node"),
  currentStep: document.querySelector("#current-step"),
  teachingStage: document.querySelector("#teaching-stage"),
  rawState: document.querySelector("#raw-state"),
  rawSolution: document.querySelector("#raw-solution"),
  rawVerification: document.querySelector("#raw-verification"),
  rawStrategy: document.querySelector("#raw-strategy"),
  rawStudentModel: document.querySelector("#raw-student-model"),
  solutionReady: document.querySelector("#solution-ready"),
  verificationReady: document.querySelector("#verification-ready"),
  strategyReady: document.querySelector("#strategy-ready"),
  summaryReady: document.querySelector("#summary-ready"),
  connectionStatus: document.querySelector("#connection-status"),
};

let busy = false;

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  })[character]);
}

function renderInlineMarkdown(source) {
  const codeSpans = [];
  let result = source.replace(/`([^`\n]+)`/g, (_, code) =>
    `TUTORCODETOKEN${codeSpans.push(code) - 1}ENDTOKEN`
  );
  result = result.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  result = result.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  return result.replace(
    /TUTORCODETOKEN(\d+)ENDTOKEN/g,
    (_, index) => `<code>${codeSpans[Number(index)]}</code>`
  );
}

function renderMarkdownBlocks(source) {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const output = [];
  let paragraph = [];
  let listType = null;
  let codeLanguage = "";
  let codeLines = null;

  const flushParagraph = () => {
    if (paragraph.length) {
      output.push(`<p>${renderInlineMarkdown(paragraph.join("<br>"))}</p>`);
      paragraph = [];
    }
  };
  const closeList = () => {
    if (listType) output.push(`</${listType}>`);
    listType = null;
  };

  for (const line of lines) {
    const fence = line.match(/^```\s*([\w+-]*)\s*$/);
    if (fence) {
      flushParagraph();
      closeList();
      if (codeLines === null) {
        codeLines = [];
        codeLanguage = fence[1];
      } else {
        const languageClass = codeLanguage ? ` class="language-${codeLanguage}"` : "";
        output.push(`<pre><code${languageClass}>${codeLines.join("\n")}</code></pre>`);
        codeLines = null;
        codeLanguage = "";
      }
      continue;
    }
    if (codeLines !== null) {
      codeLines.push(line);
      continue;
    }
    if (!line.trim()) {
      flushParagraph();
      closeList();
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      closeList();
      const level = heading[1].length;
      output.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    if (/^\s*(---+|___+|\*\*\*+)\s*$/.test(line)) {
      flushParagraph();
      closeList();
      output.push("<hr>");
      continue;
    }
    const quote = line.match(/^&gt;\s?(.*)$/);
    if (quote) {
      flushParagraph();
      closeList();
      output.push(`<blockquote>${renderInlineMarkdown(quote[1])}</blockquote>`);
      continue;
    }
    const unordered = line.match(/^\s*[-+*]\s+(.+)$/);
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      flushParagraph();
      const nextType = unordered ? "ul" : "ol";
      if (listType !== nextType) {
        closeList();
        listType = nextType;
        output.push(`<${listType}>`);
      }
      output.push(`<li>${renderInlineMarkdown((unordered || ordered)[1])}</li>`);
      continue;
    }
    closeList();
    paragraph.push(line);
  }
  if (codeLines !== null) {
    output.push(`<pre><code>${codeLines.join("\n")}</code></pre>`);
  }
  flushParagraph();
  closeList();
  return output.join("");
}

function renderMarkdown(source) {
  const math = [];
  const protectedSource = source.replace(
    /\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$[^\n$]+\$/g,
    value => `TUTORMATHTOKEN${math.push(value) - 1}ENDTOKEN`
  );
  const html = renderMarkdownBlocks(escapeHtml(protectedSource));
  return html.replace(
    /TUTORMATHTOKEN(\d+)ENDTOKEN/g,
    (_, index) => escapeHtml(math[Number(index)])
  );
}

async function typeset(element) {
  if (window.MathJax?.typesetPromise) {
    await window.MathJax.typesetPromise([element]);
  }
}

function addMessage(role, content, options = {}) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "你" : "AI";
  const bubble = document.createElement("div");
  bubble.className = `bubble${options.thinking ? " thinking" : ""}`;
  bubble.innerHTML = options.thinking ? escapeHtml(content) : renderMarkdown(content);
  article.append(avatar, bubble);
  elements.messages.append(article);
  elements.messages.scrollTop = elements.messages.scrollHeight;
  if (!options.thinking) typeset(bubble);
  return article;
}

function renderMessages(messages) {
  elements.messages.innerHTML = "";
  if (!messages.length) {
    elements.messages.innerHTML = `
      <article class="welcome-card">
        <span class="eyebrow">v0.2 LOCAL LAB</span>
        <h2>从一道题开始</h2>
        <p>输入一道新题后，系统会生成并验证解题图、建立教学策略，再进入每轮单 Agent 的教学执行。</p>
      </article>`;
    return;
  }
  messages.forEach(message => addMessage(message.role, message.content));
}

function updateRuntime(payload, replaceMessages = false) {
  const state = payload.teaching_state;
  const progress = state.teaching_progress || {};
  const runtime = payload.v02_runtime || {};
  elements.sessionId.textContent = payload.session_id;
  elements.planVersion.textContent = state.lesson_plan?.lesson_plan_version || "—";
  elements.strategyNode.textContent = progress.current_strategy_node_id || "尚未规划";
  elements.currentStep.textContent = progress.current_solution_step_id || "尚未求解";
  elements.teachingStage.textContent = progress.stage || "—";
  elements.rawState.textContent = JSON.stringify(state, null, 2);
  elements.rawSolution.textContent = JSON.stringify(state.solution, null, 2);
  elements.rawVerification.textContent = JSON.stringify(state.verification_report, null, 2);
  elements.rawStrategy.textContent = JSON.stringify(state.teaching_strategy, null, 2);
  elements.rawStudentModel.textContent = JSON.stringify(payload.student_model, null, 2);
  setArtifactStatus(elements.solutionReady, runtime.solution_ready);
  setArtifactStatus(elements.verificationReady, runtime.verification_ready);
  setArtifactStatus(elements.strategyReady, runtime.strategy_ready);
  setArtifactStatus(elements.summaryReady, runtime.summary_completed);
  renderSessions(payload.sessions || [], payload.session_id);
  if (replaceMessages) renderMessages(payload.messages || []);
}

function setArtifactStatus(element, ready) {
  element.classList.toggle("ready", Boolean(ready));
  element.title = ready ? "已生成并缓存" : "尚未生成";
}

function renderSessions(sessions, activeId) {
  elements.sessionList.innerHTML = "";
  sessions.forEach(session => {
    const button = document.createElement("button");
    button.className = `session-item${session.session_id === activeId ? " active" : ""}`;
    button.textContent = session.session_id;
    button.addEventListener("click", () => switchSession(session.session_id));
    elements.sessionList.append(button);
  });
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

function setBusy(value) {
  busy = value;
  elements.send.disabled = value;
  elements.newChat.disabled = value;
  elements.question.disabled = value;
}

async function submitQuestion(event) {
  event.preventDefault();
  const question = elements.question.value.trim();
  if (!question || busy) return;
  addMessage("user", question);
  elements.question.value = "";
  setBusy(true);
  const thinking = addMessage("assistant", "v0.2 正在执行；新题首轮会依次求解、验证和规划", { thinking: true });
  try {
    const payload = await request("/api/chat", {
      method: "POST",
      body: JSON.stringify({ question }),
    });
    thinking.remove();
    addMessage("assistant", payload.answer);
    updateRuntime(payload);
  } catch (error) {
    thinking.remove();
    addMessage("assistant", `请求失败：${error.message}`);
  } finally {
    setBusy(false);
    elements.question.focus();
  }
}

async function newSession() {
  if (busy) return;
  try {
    setBusy(true);
    const payload = await request("/api/sessions/new", { method: "POST", body: "{}" });
    updateRuntime(payload, true);
  } catch (error) {
    alert(`新建会话失败：${error.message}`);
  } finally {
    setBusy(false);
  }
}

async function switchSession(sessionId) {
  if (busy) return;
  try {
    setBusy(true);
    const payload = await request("/api/sessions/switch", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    });
    updateRuntime(payload, true);
  } catch (error) {
    alert(`切换会话失败：${error.message}`);
  } finally {
    setBusy(false);
  }
}

elements.composer.addEventListener("submit", submitQuestion);
elements.newChat.addEventListener("click", newSession);
elements.question.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.composer.requestSubmit();
  }
});

request("/api/bootstrap")
  .then(payload => {
    updateRuntime(payload, true);
    elements.connectionStatus.textContent = "本地已连接";
    elements.question.focus();
  })
  .catch(error => {
    elements.connectionStatus.textContent = "连接失败";
    elements.connectionStatus.classList.add("error");
    addMessage("assistant", `无法连接本地服务：${error.message}`);
  });
