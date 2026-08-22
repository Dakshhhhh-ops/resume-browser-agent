import { useCallback, useEffect, useState } from "react";
import "./App.css";

const API_URL =
  import.meta.env.VITE_API_URL || "http://127.0.0.1:8010";

/**
 * Read a JSON response, surfacing FastAPI's `detail` as the error text.
 */
async function readJson(response) {
  let data = null;

  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    const detail =
      (data && (data.detail || data.message)) ||
      `Request failed (${response.status})`;

    throw new Error(detail);
  }

  return data;
}

function App() {
  const [resume, setResume] = useState(null);
  const [resumePath, setResumePath] = useState("");
  const [profile, setProfile] = useState(null);
  const [summary, setSummary] = useState(null);

  const [jobs, setJobs] = useState([]);
  const [matches, setMatches] = useState([]);
  const [applications, setApplications] = useState([]);

  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [online, setOnline] = useState(null);
  const [pendingJob, setPendingJob] = useState(null);

  const loading = Boolean(busy);

  // ── Backend status + saved applications ────────────────────

  const loadApplications = useCallback(async () => {
    try {
      const data = await readJson(
        await fetch(`${API_URL}/api/applications`)
      );

      setApplications(data.applications || []);
    } catch {
      // Non-fatal: the dashboard just stays empty.
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    const ping = async () => {
      try {
        const response = await fetch(`${API_URL}/api/health`);

        if (!cancelled) {
          setOnline(response.ok);
        }
      } catch {
        if (!cancelled) {
          setOnline(false);
        }
      }
    };

    ping();
    loadApplications();

    return () => {
      cancelled = true;
    };
  }, [loadApplications]);

  // ── Phase 1: resume ────────────────────────────────────────

  const handleResumeChange = (e) => {
    const file = e.target.files[0];

    if (file && file.type === "application/pdf") {
      setResume(file);
      setError("");
    } else {
      setResume(null);
      setError("Please upload a PDF resume.");
    }
  };

  const parseResume = async () => {
    if (!resume) {
      setError("Please upload your resume first.");
      return;
    }

    setBusy("parse");
    setError("");
    setNotice("");

    try {
      const formData = new FormData();
      formData.append("file", resume);

      const data = await readJson(
        await fetch(`${API_URL}/api/resume/parse`, {
          method: "POST",
          body: formData,
        })
      );

      setProfile(data.profile);
      setSummary(data.summary);
      setResumePath(data.resume_path);

      setJobs([]);
      setMatches([]);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  };

  // ── Phase 2: discovery ─────────────────────────────────────

  const fetchJobs = async () => {
    setBusy("jobs");
    setError("");
    setNotice("");

    try {
      const data = await readJson(
        await fetch(`${API_URL}/api/jobs`)
      );

      setJobs(data.jobs || []);
      setMatches([]);

      setNotice(
        `Fetched ${data.count} listings from ` +
          `${(data.companies || []).join(", ")}.`
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  };

  // ── Phase 3: ranking ───────────────────────────────────────

  const rankJobs = async () => {
    if (!profile) {
      setError("Analyze your resume first.");
      return;
    }

    setBusy("rank");
    setError("");
    setNotice("");

    try {
      const data = await readJson(
        await fetch(`${API_URL}/api/jobs/rank`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ resume: profile, top_n: 3 }),
        })
      );

      setMatches(data.jobs || []);

      if (!data.count) {
        setNotice("No eligible technical matches were found.");
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  };

  // ── Phase 4: application ───────────────────────────────────

  const confirmApply = async () => {
    const job = pendingJob;

    setPendingJob(null);
    setBusy("apply");
    setError("");
    setNotice("");

    try {
      const data = await readJson(
        await fetch(`${API_URL}/api/apply`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            job,
            resume: profile,
            resume_path: resumePath,
            approved: true,
          }),
        })
      );

      if (data.success) {
        setNotice(
          `${data.message} — ${job.title} @ ${job.company}`
        );

        await loadApplications();
      } else {
        setError(
          `${data.message}${
            data.stage ? ` (stage: ${data.stage})` : ""
          }`
        );
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  };

  const eligibilityClass = (status) => {
    if (status === "Eligible") return "pill pill-good";
    if (status === "Ineligible") return "pill pill-bad";
    return "pill pill-warn";
  };

  const scoreClass = (score) => {
    if (score >= 80) return "score score-high";
    if (score >= 60) return "score score-mid";
    return "score score-low";
  };

  return (
    <div className="app">
      <nav className="navbar">
        <div className="logo">
          Resume<span>Agent</span>
        </div>

        <div className="nav-status">
          <span
            className={`status-dot ${
              online === false ? "status-dot-off" : ""
            }`}
          ></span>
          {online === null
            ? "Connecting…"
            : online
              ? "Backend Connected"
              : "Backend Offline"}
        </div>
      </nav>

      <main className="container">
        <section className="hero">
          <div className="badge">AI-POWERED JOB DISCOVERY</div>

          <h1>
            Find jobs that
            <br />
            <span>actually fit you.</span>
          </h1>

          <p>
            Upload your resume and let AI analyze your profile,
            discover relevant jobs, rank them, and help you apply.
          </p>
        </section>

        <section className="upload-card">
          <div className="upload-icon">↑</div>

          <h2>Upload your resume</h2>

          <p>PDF format required</p>

          <label className="upload-button">
            {resume ? "Change Resume" : "Choose Resume"}

            <input
              type="file"
              accept=".pdf"
              onChange={handleResumeChange}
            />
          </label>

          {resume && (
            <div className="file-name">📄 {resume.name}</div>
          )}

          <button
            className="primary-button"
            onClick={parseResume}
            disabled={loading || !resume}
          >
            {busy === "parse"
              ? "Analyzing Resume…"
              : "Analyze Resume →"}
          </button>
        </section>

        {error && <div className="error">{error}</div>}
        {notice && <div className="notice">{notice}</div>}

        {summary && (
          <section className="profile-section">
            <div className="section-header">
              <div>
                <span className="section-label">PHASE 1</span>
                <h2>Candidate Profile</h2>
              </div>
            </div>

            <div className="profile-grid">
              <div className="profile-card">
                <span>Name</span>
                <strong>{summary.name}</strong>
              </div>

              <div className="profile-card">
                <span>Level</span>
                <strong>{summary.level}</strong>
              </div>

              <div className="profile-card">
                <span>Education</span>
                <strong>{summary.education}</strong>
              </div>

              <div className="profile-card">
                <span>Contact</span>
                <strong>
                  {summary.email}
                  <br />
                  {summary.phone}
                </strong>
              </div>
            </div>

            <div className="tag-block">
              <span className="tag-label">Languages</span>
              <div className="tags">
                {(summary.languages || []).map((item) => (
                  <span className="tag" key={item}>
                    {item}
                  </span>
                ))}
              </div>
            </div>

            <div className="tag-block">
              <span className="tag-label">Frameworks</span>
              <div className="tags">
                {(summary.frameworks || []).map((item) => (
                  <span className="tag" key={item}>
                    {item}
                  </span>
                ))}
              </div>
            </div>

            <div className="tag-block">
              <span className="tag-label">Keywords</span>
              <div className="tags">
                {(summary.keywords || []).map((item) => (
                  <span className="tag tag-muted" key={item}>
                    {item}
                  </span>
                ))}
              </div>
            </div>

            <button
              className="secondary-button"
              onClick={fetchJobs}
              disabled={loading}
            >
              {busy === "jobs"
                ? "Fetching Listings…"
                : "Discover Jobs →"}
            </button>
          </section>
        )}

        {jobs.length > 0 && (
          <section className="jobs-section">
            <div className="section-header">
              <div>
                <span className="section-label">PHASE 2</span>
                <h2>Discovered Listings</h2>
              </div>

              <span className="job-count">{jobs.length} jobs</span>
            </div>

            <div className="jobs-grid">
              {jobs.slice(0, 9).map((job) => (
                <div className="job-card" key={job.job_id}>
                  <div className="job-top">
                    <span className="company">{job.company}</span>
                  </div>

                  <h3>{job.title}</h3>

                  <p className="location">📍 {job.location}</p>

                  <a
                    className="apply-button"
                    href={job.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    View Job →
                  </a>
                </div>
              ))}
            </div>

            <button
              className="secondary-button"
              onClick={rankJobs}
              disabled={loading}
            >
              {busy === "rank"
                ? "Ranking Top Matches…"
                : "Rank My Top Matches →"}
            </button>
          </section>
        )}

        {matches.length > 0 && (
          <section className="jobs-section">
            <div className="section-header">
              <div>
                <span className="section-label">PHASE 3</span>
                <h2>Top Matches</h2>
              </div>

              <span className="job-count">
                {matches.length} ranked
              </span>
            </div>

            <div className="match-list">
              {matches.map((job, index) => (
                <div
                  className="match-card"
                  key={job.job_id || index}
                >
                  <div className="match-head">
                    <div>
                      <span className="rank">
                        #{job.rank || index + 1}
                      </span>

                      <h3>{job.title}</h3>

                      <p className="company">
                        {job.company} · {job.location}
                      </p>
                    </div>

                    <div className="match-scores">
                      <span
                        className={scoreClass(job.tech_score || 0)}
                      >
                        {job.tech_score || 0}
                        <small>/100</small>
                      </span>

                      <span
                        className={eligibilityClass(
                          job.eligibility_status
                        )}
                      >
                        {job.eligibility_status ||
                          "Requires Verification"}
                      </span>
                    </div>
                  </div>

                  {job.match_reason && (
                    <p className="reason">{job.match_reason}</p>
                  )}

                  {(job.eligibility_breakdown || []).length > 0 && (
                    <ul className="breakdown">
                      {job.eligibility_breakdown.map((line, i) => (
                        <li key={i}>{line}</li>
                      ))}
                    </ul>
                  )}

                  <div className="skill-columns">
                    <div>
                      <span className="tag-label">
                        Matching Skills
                      </span>
                      <div className="tags">
                        {(job.matching_skills || []).map((s) => (
                          <span className="tag tag-good" key={s}>
                            {s}
                          </span>
                        ))}
                      </div>
                    </div>

                    <div>
                      <span className="tag-label">Gaps</span>
                      <div className="tags">
                        {(job.gaps || []).length ? (
                          job.gaps.map((g) => (
                            <span className="tag tag-warn" key={g}>
                              {g}
                            </span>
                          ))
                        ) : (
                          <span className="tag tag-muted">
                            None identified
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="match-actions">
                    <a
                      className="apply-button"
                      href={job.url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      View Posting
                    </a>

                    <button
                      className="primary-button inline"
                      onClick={() => setPendingJob(job)}
                      disabled={loading}
                    >
                      {busy === "apply"
                        ? "Agent Working…"
                        : "Apply with Agent →"}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {applications.length > 0 && (
          <section className="jobs-section">
            <div className="section-header">
              <div>
                <span className="section-label">PHASE 4</span>
                <h2>Submitted Applications</h2>
              </div>

              <span className="job-count">
                {applications.length} submitted
              </span>
            </div>

            <div className="applications">
              {applications.map((item, index) => (
                <div
                  className="application-row"
                  key={item.job_id || index}
                >
                  <div>
                    <strong>{item.title}</strong>
                    <p className="company">
                      {item.company} · {item.location}
                    </p>
                  </div>

                  <span className="pill pill-good">
                    {item.status}
                  </span>
                </div>
              ))}
            </div>
          </section>
        )}
      </main>

      {pendingJob && (
        <div
          className="modal-backdrop"
          onClick={() => setPendingJob(null)}
        >
          <div
            className="modal"
            onClick={(e) => e.stopPropagation()}
          >
            <h3>Authorize submission</h3>

            <p>
              The agent will open a real browser, fill the Greenhouse
              form for <strong>{pendingJob.title}</strong> at{" "}
              <strong>{pendingJob.company}</strong>, attach your
              resume, and <strong>submit the application</strong>.
            </p>

            <p className="modal-warning">
              This action is irreversible — a real application will be
              sent on your behalf.
            </p>

            <div className="modal-actions">
              <button
                className="secondary-button"
                onClick={() => setPendingJob(null)}
              >
                Cancel
              </button>

              <button
                className="primary-button inline"
                onClick={confirmApply}
              >
                Yes, submit it
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
