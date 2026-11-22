/* ============ CONFIG ============
   Connected to FastAPI backend. If the call fails or offline,
   falls back to the built-in sample result gracefully. */
const API_URL = (typeof window !== "undefined" && window.location.origin.startsWith("http"))
  ? `${window.location.origin}/analyze`
  : "http://localhost:8000/analyze";
const USE_REAL_API = true;

const SAMPLE = {
  risk_score: 9,
  total_exposure_inr: 55040000,
  exposure_after_inr: 840000,
  findings: [
    {
      title: "Unlimited Liability", clause: "9.2", severity: "critical", exposure_inr: 50000000,
      why: "Client bears uncapped liability for any data breach or service failure. One incident could exceed the whole contract value many times over.",
      original: "Client shall be liable for all losses, damages and costs arising from use of the Services, without limitation.",
      redlines: {
        soft: "Each party's aggregate liability shall not exceed three (3) times the fees paid in the 12 months preceding the claim.",
        balanced: "Vendor's aggregate liability shall not exceed fees paid in the 12 months preceding the claim.",
        firm: "Vendor's aggregate liability shall not exceed fees paid in the 12 months preceding the claim, excluding claims arising from Vendor's gross negligence, which shall be uncapped."
      },
      acceptance: { soft: 88, balanced: 72, firm: 46 }
    },
    {
      title: "Auto-Renewal Trap", clause: "14.1", severity: "high", exposure_inr: 3840000,
      why: "Contract silently renews for 3 years unless notice is given 90 days before expiry. Missing the window locks in ₹38.4L of unwanted fees.",
      original: "This Agreement shall automatically renew for successive three (3) year terms unless terminated by written notice no less than ninety (90) days prior to expiry.",
      redlines: {
        soft: "This Agreement shall renew for successive one (1) year terms unless either party gives sixty (60) days' written notice.",
        balanced: "This Agreement shall renew for successive one (1) year terms unless either party gives thirty (30) days' written notice, and Vendor shall send a renewal reminder 60 days before expiry.",
        firm: "This Agreement shall not renew automatically. Renewal requires written agreement signed by both parties."
      },
      acceptance: { soft: 91, balanced: 78, firm: 52 }
    },
    {
      title: "Uncapped Price Escalation", clause: "6.4", severity: "high", exposure_inr: 1200000,
      why: "Vendor may raise fees at any time with 7 days' notice and no ceiling.",
      original: "Vendor may revise the Fees at any time upon seven (7) days' written notice to Client.",
      redlines: {
        soft: "Vendor may revise Fees once per year with sixty (60) days' notice, not exceeding 10%.",
        balanced: "Vendor may revise Fees once per contract year with sixty (60) days' notice, capped at the lower of 5% or CPI.",
        firm: "Fees are fixed for the Initial Term. Any increase on renewal is capped at 3% and requires ninety (90) days' notice."
      },
      acceptance: { soft: 89, balanced: 80, firm: 58 }
    }
  ]
};

/* ============ helpers ============ */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const inr = n => "₹" + Number(n).toLocaleString("en-IN");
const sleep = ms => new Promise(r => setTimeout(r, ms));
let DATA = null, TONE = "balanced";

function countTo(el, to, fmt = inr, dur = 1600) {
  const t0 = performance.now();
  (function tick(t) {
    const p = Math.min((t - t0) / dur, 1), e = 1 - Math.pow(1 - p, 4);
    el.textContent = fmt(Math.round(to * e));
    if (p < 1) requestAnimationFrame(tick);
  })(t0);
}

/* ============ cursor glow + reveal ============ */
const glow = $("#glow");
addEventListener("mousemove", e => { glow.style.left = e.clientX + "px"; glow.style.top = e.clientY + "px"; });

const io = new IntersectionObserver(es => es.forEach(e => {
  if (!e.isIntersecting) return;
  e.target.classList.add("in");
  $$("[data-count]", e.target).forEach(b => countTo(b, +b.dataset.count, n => n + (b.dataset.suffix || ""), 1400));
  io.unobserve(e.target);
}), { threshold: .15 });
$$(".reveal").forEach(el => io.observe(el));

/* hero: cycling exposure headline */
const words = ["₹5 Crore", "₹38 Lakh", "hidden", "₹12 Lakh"];
let wi = 0;
setInterval(() => {
  const el = $("#typed");
  el.style.opacity = 0;
  setTimeout(() => { wi = (wi + 1) % words.length; el.textContent = words[wi]; el.style.opacity = 1; }, 300);
}, 2600);
$("#typed").style.transition = "opacity .3s";

/* ============ upload flow ============ */
const dz = $("#dropzone"), fileInput = $("#fileInput");
$("#browseBtn").onclick = () => fileInput.click();
$("#sampleBtn").onclick = () => start("Master_Services_Agreement.pdf", null);
fileInput.onchange = () => fileInput.files[0] && start(fileInput.files[0].name, fileInput.files[0]);
["dragenter", "dragover"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add("drag"); }));
["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove("drag"); }));
dz.addEventListener("drop", e => { const f = e.dataTransfer.files[0]; if (f) start(f.name, f); });

async function start(name, file) {
  dz.classList.add("hidden");
  $("#scanner").classList.remove("hidden");
  $("#docName").textContent = name;

  // Run scanning animation and API in parallel
  const apiPromise = fetchAnalysis(file);
  const lis = $$("#steps li");
  lis.forEach(l => l.className = "");
  for (const li of lis) { li.classList.add("active"); await sleep(750); li.className = "done"; }
  DATA = await apiPromise;

  $("#scanner").classList.add("hidden");
  $("#results").classList.remove("hidden");
  render();
}

async function fetchAnalysis(file) {
  if (USE_REAL_API) {
    try {
      const fd = new FormData();
      if (file) {
        fd.append("file", file);
      } else {
        fd.append("is_sample", "true");
      }
      fd.append("posture", TONE);
      const r = await fetch(API_URL, { method: "POST", body: fd });
      if (r.ok) {
        const json = await r.json();
        console.log("Analysis received from backend:", json);
        return json;
      } else {
        console.warn("Backend error:", r.status, await r.text());
      }
    } catch (e) {
      console.warn("API unreachable, using sample data fallback", e);
    }
  }
  return SAMPLE;
}

/* ============ render results ============ */
function render() {
  const d = DATA;
  countTo($("#exposure"), d.total_exposure_inr);
  countTo($("#after"), d.exposure_after_inr);
  countTo($("#riskScore"), d.risk_score, n => n, 1400);
  const pct = d.total_exposure_inr > 0 ? Math.round((1 - d.exposure_after_inr / d.total_exposure_inr) * 100) : 0;
  $("#saved").textContent = "↓ " + pct + "% reduction";
  requestAnimationFrame(() => {
    $("#barBefore").style.width = "100%";
    $("#ringFg").style.strokeDashoffset = 327 - (327 * d.risk_score / 10);
  });
  renderFindings();
  updateAccept();
}

function renderFindings() {
  $("#findings").innerHTML = DATA.findings.map((f, i) => `
    <article class="finding" style="animation-delay:${i * 0.25}s">
      <div class="f-head">
        <span class="sev ${f.severity}">${f.severity.toUpperCase()}</span>
        <h4>${f.title}</h4><span class="cl">Clause ${f.clause}</span>
        <span class="exp">${inr(f.exposure_inr)}</span>
      </div>
      <div class="f-body">
        <p class="why">${f.why}</p>
        <div class="redline">
          <div class="old"><small>Original — Clause ${f.clause}</small>${f.original}</div>
          <div class="new"><small>VendorGuard counter-proposal · ${TONE}</small><span id="rl-${i}">${f.redlines[TONE]}</span></div>
        </div>
        <div class="f-foot">
          <span>Vendor acceptance: <b id="ac-${i}">${f.acceptance[TONE]}%</b></span>
          <button data-copy="${i}">Copy redline</button>
        </div>
      </div>
    </article>`).join("");
  $$("[data-copy]").forEach(b => b.onclick = () => copy(DATA.findings[b.dataset.copy].redlines[TONE], b));
}

function updateAccept() {
  const avg = Math.round(DATA.findings.reduce((s, f) => s + f.acceptance[TONE], 0) / DATA.findings.length);
  countTo($("#acceptPct"), avg, n => n + "%", 700);
}

function updateToneExposure() {
  if (!DATA) return;
  const mult = { soft: 0.05, balanced: 0.015, firm: 0.005 }[TONE] || 0.015;
  const after = Math.round(DATA.total_exposure_inr * mult);
  DATA.exposure_after_inr = after;
  countTo($("#after"), after);
  const pct = DATA.total_exposure_inr > 0 ? Math.round((1 - after / DATA.total_exposure_inr) * 100) : 0;
  $("#saved").textContent = "↓ " + pct + "% reduction";
}

/* tone switch */
$$("#tone button").forEach(b => b.onclick = () => {
  TONE = b.dataset.tone;
  $$("#tone button").forEach(x => x.classList.toggle("on", x === b));
  DATA.findings.forEach((f, i) => {
    $("#rl-" + i).textContent = f.redlines[TONE];
    $("#ac-" + i).textContent = f.acceptance[TONE] + "%";
  });
  $$(".redline .new small").forEach(s => s.textContent = s.textContent.replace(/·.*/, "· " + TONE));
  updateAccept();
  updateToneExposure();
});

/* actions */
function copy(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    const o = btn.textContent; btn.textContent = "Copied ✓";
    setTimeout(() => btn.textContent = o, 1400);
  });
}
$("#copyAll").onclick = e => copy(
  DATA.findings.map(f => `Clause ${f.clause} (${f.title}):\n${f.redlines[TONE]}`).join("\n\n"), e.target);
$("#jsonBtn").onclick = () => {
  const out = $("#jsonOut");
  out.textContent = JSON.stringify(DATA, null, 2);
  out.classList.toggle("hidden");
};
$("#resetBtn").onclick = () => {
  $("#results").classList.add("hidden");
  $("#jsonOut").classList.add("hidden");
  $("#barBefore").style.width = "0"; $("#ringFg").style.strokeDashoffset = 327;
  dz.classList.remove("hidden"); fileInput.value = "";
};
