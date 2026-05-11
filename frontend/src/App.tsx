import {
  Activity,
  ArrowLeft,
  ArrowUpRight,
  BriefcaseBusiness,
  CheckCircle2,
  Database,
  FileText,
  Link as LinkIcon,
  Loader2,
  Mail,
  MapPin,
  Phone,
  Search,
  Save,
  Upload,
} from 'lucide-react';
import { ChangeEvent, useEffect, useMemo, useRef, useState } from 'react';
import { BrowserRouter, Link, Route, Routes, useNavigate, useParams } from 'react-router-dom';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000';
const EXPECTED_PROCESS_SECONDS = 60;

type CvStats = {
  cv_count: number;
  latest_upload_at: string | null;
  average_openrouter_duration_seconds: number | null;
  average_page_count: number | null;
  job_count: number;
};

type StructuredCv = {
  name: string | null;
  email: string | null;
  phone: string | null;
  location: string | null;
  summary: string | null;
  skills: string[];
  experience: Array<Record<string, unknown>>;
  education: Array<Record<string, unknown>>;
  certifications: string[];
  links: string[];
  preferred_roles: string[];
  preferred_locations: string[];
  salary_expectation: string | null;
};

type WorkingArrangement = 'on_site' | 'hybrid' | 'remote';

type CvPreferences = {
  preferred_location: string | null;
  salary_min: number | null;
  salary_max: number | null;
  working_arrangements: WorkingArrangement[];
  industry_keyword: string | null;
};

type UploadedCv = {
  id: string;
  original_filename: string | null;
  file_size_bytes: number;
  page_count: number;
  model: string;
  openrouter_duration_seconds: number | null;
  preferences: CvPreferences;
  plain_text: string;
  structured: StructuredCv;
  created_at: string;
};

type UploadState = 'idle' | 'uploading' | 'success' | 'error';
type MatchState = 'idle' | 'matching' | 'success' | 'error';

type Category = {
  tag: string;
  label: string;
};

type Company = {
  id: number;
  display_name: string;
};

type Location = {
  id: number;
  display_name: string;
  area: string[];
};

type JobSummary = {
  adzuna_id: string;
  title: string;
  description: string | null;
  redirect_url: string | null;
  created_at: string | null;
  scraped_at: string;
  updated_at: string;
  salary_min: number | null;
  salary_max: number | null;
  salary_is_predicted: boolean;
  contract_type: string | null;
  contract_time: string | null;
  category: Category | null;
  company: Company | null;
  location: Location | null;
};

type JobDetail = JobSummary & {
  adref: string | null;
  raw_json: Record<string, unknown> | null;
};

type CvMatchRun = {
  id: number;
  cv_document_id: string;
  status: 'running' | 'success' | 'failed';
  retrieve_count: number;
  rrf_k: number;
  index_fingerprint: string | null;
  index_model: string | null;
  started_at: string;
  finished_at: string | null;
  error_message: string | null;
};

type CvJobMatch = {
  id: number;
  run_id: number;
  cv_document_id: string;
  job: JobSummary;
  rank: number;
  bm25_rank: number | null;
  dense_rank: number | null;
  rrf_score: number;
  bm25_score: number;
  dense_score: number;
  preference_filters: Record<string, unknown>;
  created_at: string;
};

type CvMatchesResponse = {
  run: CvMatchRun;
  matches: CvJobMatch[];
};

type CvMatchAnalysis = {
  id: number;
  match_id: number;
  run_id: number;
  cv_document_id: string;
  job_id: string;
  status: 'running' | 'success' | 'failed';
  model: string | null;
  seniority_fit: number | null;
  tech_overlap: number | null;
  domain_fit: number | null;
  responsibilities_fit: number | null;
  location_fit: number | null;
  overall: number | null;
  strengths: string[];
  concerns: string[];
  summary: string | null;
  started_at: string;
  finished_at: string | null;
  error_message: string | null;
};

type CvMatchDetailResponse = {
  run: CvMatchRun;
  match: CvJobMatch;
  job: JobDetail;
  analysis: CvMatchAnalysis | null;
};

function formatNumber(value: number | null | undefined) {
  if (value == null) return 'Not yet';
  return new Intl.NumberFormat('en-GB').format(value);
}

function formatBytes(value: number | null | undefined) {
  if (value == null) return 'Unknown';
  return new Intl.NumberFormat('en-GB', {
    maximumFractionDigits: 1,
    minimumFractionDigits: 0,
  }).format(value / 1024);
}

function formatSeconds(value: number | null | undefined) {
  if (value == null) return 'Not yet';
  return `${value.toFixed(1)}s`;
}

function formatDate(value: string | null) {
  if (!value) return 'No uploads yet';
  return new Intl.DateTimeFormat('en-GB', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function formatCurrency(value: number | null | undefined) {
  if (value == null) return null;
  return new Intl.NumberFormat('en-GB', {
    maximumFractionDigits: 0,
    style: 'currency',
    currency: 'GBP',
  }).format(value);
}

function formatSalary(job: JobSummary) {
  const min = formatCurrency(job.salary_min);
  const max = formatCurrency(job.salary_max);
  if (min && max && min !== max) return `${min} - ${max}`;
  return min ?? max ?? 'Salary not listed';
}

const JOB_KEYWORD_PATTERNS: Array<[string, RegExp]> = [
  ['AI', /\b(ai|artificial intelligence)\b/i],
  ['Data', /\bdata\b/i],
  ['Platform', /\bplatform\b/i],
  ['Python', /\bpython\b/i],
  ['JavaScript', /\bjavascript\b/i],
  ['TypeScript', /\btypescript\b/i],
  ['React', /\breact\b/i],
  ['Node.js', /\bnode\.?js\b/i],
  ['AWS', /\baws\b/i],
  ['Azure', /\bazure\b/i],
  ['GCP', /\bgcp|google cloud\b/i],
  ['Kubernetes', /\bkubernetes|k8s\b/i],
  ['Docker', /\bdocker\b/i],
  ['SQL', /\bsql\b/i],
  ['PostgreSQL', /\bpostgres(?:ql)?\b/i],
  ['Machine learning', /\bmachine learning|ml\b/i],
  ['LLM', /\bllm|large language model\b/i],
  ['Fintech', /\bfintech\b/i],
  ['Security', /\bsecurity\b/i],
  ['DevOps', /\bdevops\b/i],
  ['Architecture', /\barchitecture|architect\b/i],
  ['Leadership', /\bleadership|lead|manager|head of\b/i],
  ['Delivery', /\bdelivery\b/i],
  ['Agile', /\bagile|scrum\b/i],
  ['API', /\bapi|apis\b/i],
  ['Analytics', /\banalytics\b/i],
  ['Cloud', /\bcloud\b/i],
  ['Hybrid', /\bhybrid\b/i],
  ['Remote', /\bremote\b/i],
];

function friendlyLabel(value: string | null | undefined) {
  if (!value) return null;
  return value
    .replace(/-/g, ' ')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function jobKeywordTags(job: JobSummary) {
  const tags: string[] = [];
  const addTag = (tag: string | null | undefined) => {
    if (tag && !tags.includes(tag)) tags.push(tag);
  };

  addTag(job.category?.label ?? friendlyLabel(job.category?.tag));
  addTag(friendlyLabel(job.contract_type));
  addTag(friendlyLabel(job.contract_time));

  const text = `${job.title} ${job.description ?? ''}`;
  for (const [label, pattern] of JOB_KEYWORD_PATTERNS) {
    if (pattern.test(text)) addTag(label);
  }

  return tags.slice(0, 10);
}

function divLabScore(score: number, maxScore: number) {
  if (maxScore <= 0) return 0;
  return Math.max(1, Math.round((score / maxScore) * 100));
}

function scorePercent(value: number | null) {
  if (value == null) return 0;
  return Math.max(0, Math.min(100, value * 10));
}

function rawJsonPreview(value: Record<string, unknown> | null) {
  if (!value) return 'No raw payload stored.';
  return JSON.stringify(value, null, 2);
}

function textValue(value: unknown) {
  if (value == null || value === '') return 'Not listed';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (Array.isArray(value)) return value.join(', ');
  return String(value);
}

function StatCard({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="stat-card">
      <div className="stat-icon">{icon}</div>
      <div>
        <p className="stat-label">{label}</p>
        <p className="stat-value">{value}</p>
      </div>
    </div>
  );
}

function AppHeader() {
  return (
    <header className="top-bar">
      <Link className="brand-mark" to="/">
        DL9K
      </Link>
      <div>
        <p className="eyebrow">Candidate intelligence workspace</p>
        <h1>DivLab9000</h1>
        <p className="tagline">Division of Labour as-a-service</p>
      </div>
    </header>
  );
}

function LandingPage() {
  const navigate = useNavigate();
  const [stats, setStats] = useState<CvStats | null>(null);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [uploadState, setUploadState] = useState<UploadState>('idle');
  const [progress, setProgress] = useState(0);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  async function loadStats() {
    try {
      setStatsError(null);
      const response = await fetch(`${API_BASE_URL}/cvs/stats`);
      if (!response.ok) throw new Error(`Stats request failed with ${response.status}`);
      setStats(await response.json());
    } catch (error) {
      setStatsError(error instanceof Error ? error.message : 'Unable to load stats');
    }
  }

  useEffect(() => {
    void loadStats();
  }, []);

  useEffect(() => {
    if (uploadState !== 'uploading') return undefined;

    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      const elapsedSeconds = (Date.now() - startedAt) / 1000;
      const nextProgress = Math.min((elapsedSeconds / EXPECTED_PROCESS_SECONDS) * 95, 95);
      setProgress(nextProgress);
    }, 250);

    return () => window.clearInterval(timer);
  }, [uploadState]);

  const progressLabel = useMemo(() => {
    if (uploadState === 'uploading') return 'Extracting CV profile';
    if (uploadState === 'success') return 'Extraction complete';
    if (uploadState === 'error') return 'Extraction failed';
    return 'Ready for upload';
  }, [uploadState]);

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setSelectedFile(file);
    setUploadError(null);
    setUploadState('idle');
    setProgress(0);
  }

  async function uploadCv() {
    if (!selectedFile) {
      fileInputRef.current?.click();
      return;
    }

    setUploadState('uploading');
    setUploadError(null);
    setProgress(3);

    const formData = new FormData();
    formData.append('file', selectedFile);

    try {
      const response = await fetch(`${API_BASE_URL}/cvs/upload`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const errorBody = await response.json().catch(() => null);
        throw new Error(errorBody?.detail ?? `Upload failed with ${response.status}`);
      }

      const cv = (await response.json()) as UploadedCv;
      setProgress(100);
      setUploadState('success');
      await loadStats();
      navigate(`/cvs/${cv.id}`);
    } catch (error) {
      setUploadState('error');
      setUploadError(error instanceof Error ? error.message : 'Upload failed');
    }
  }

  return (
    <main className="page-shell">
      <AppHeader />

      <section className="hero">
        <div className="hero-copy">
          <p className="section-kicker">Local demo service</p>
          <h2>Turn CVs into structured matching profiles.</h2>
          <p>
            Upload a candidate CV, extract clean text and structured profile data, then use the
            result against the local job corpus. The current workflow is synchronous and designed
            for inspection, iteration, and quick demos.
          </p>
          <div className="hero-actions">
            <input
              ref={fileInputRef}
              className="file-input"
              type="file"
              accept="application/pdf,.pdf"
              onChange={handleFileChange}
            />
            <button className="primary-button" type="button" onClick={uploadCv}>
              {uploadState === 'uploading' ? (
                <Loader2 className="spin" size={20} />
              ) : (
                <Upload size={20} />
              )}
              {selectedFile ? 'Upload CV' : 'Choose CV'}
            </button>
            {selectedFile ? <span className="file-name">{selectedFile.name}</span> : null}
          </div>
        </div>

        <div className="upload-panel">
          <div className="upload-panel-header">
            <div>
              <p className="panel-label">Synchronous extraction</p>
              <h3>{progressLabel}</h3>
            </div>
            {uploadState === 'success' ? (
              <CheckCircle2 className="success-icon" size={28} />
            ) : (
              <Activity className="muted-icon" size={28} />
            )}
          </div>
          <div className="progress-track" aria-label="CV extraction progress">
            <div className="progress-bar" style={{ width: `${progress}%` }} />
          </div>
          <div className="progress-meta">
            <span>{Math.round(progress)}%</span>
            <span>Assumes about {EXPECTED_PROCESS_SECONDS}s processing time</span>
          </div>
          {uploadError ? <p className="error-message">{uploadError}</p> : null}
        </div>
      </section>

      <section className="stats-section">
        <div className="section-heading">
          <p className="section-kicker">Corpus status</p>
          <h2>CV database snapshot</h2>
        </div>
        {statsError ? <p className="error-message">{statsError}</p> : null}
        <div className="stats-grid">
          <StatCard
            icon={<FileText size={22} />}
            label="CVs uploaded"
            value={formatNumber(stats?.cv_count)}
          />
          <StatCard
            icon={<Activity size={22} />}
            label="Avg OpenRouter time"
            value={formatSeconds(stats?.average_openrouter_duration_seconds)}
          />
          <StatCard
            icon={<Database size={22} />}
            label="Avg page count"
            value={
              stats?.average_page_count == null ? 'Not yet' : stats.average_page_count.toFixed(1)
            }
          />
          <StatCard
            icon={<BriefcaseBusiness size={22} />}
            label="Jobs indexed"
            value={formatNumber(stats?.job_count)}
          />
        </div>
        <div className="latest-row">
          <span>Latest CV upload</span>
          <strong>{formatDate(stats?.latest_upload_at ?? null)}</strong>
          <a href={`${API_BASE_URL}/docs`} target="_blank" rel="noreferrer">
            API docs <ArrowUpRight size={16} />
          </a>
        </div>
      </section>
    </main>
  );
}

function DetailField({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string | null;
}) {
  return (
    <div className="detail-field">
      <div className="detail-field-icon">{icon}</div>
      <div>
        <p>{label}</p>
        <strong>{value || 'Not listed'}</strong>
      </div>
    </div>
  );
}

function ChipList({ items }: { items: string[] }) {
  if (items.length === 0) return <p className="muted-text">Not listed</p>;
  return (
    <div className="chip-list">
      {items.map((item) => (
        <span key={item}>{item}</span>
      ))}
    </div>
  );
}

function TimelineList({
  items,
  emptyLabel,
}: {
  items: Array<Record<string, unknown>>;
  emptyLabel: string;
}) {
  if (items.length === 0) return <p className="muted-text">{emptyLabel}</p>;
  return (
    <div className="timeline-list">
      {items.map((item, index) => (
        <article className="timeline-item" key={`${textValue(item.title)}-${index}`}>
          <div>
            <h4>{textValue(item.title ?? item.qualification ?? item.institution)}</h4>
            <p>{textValue(item.company ?? item.institution ?? item.field)}</p>
          </div>
          <dl>
            <div>
              <dt>Dates</dt>
              <dd>
                {textValue(item.start_date)} - {textValue(item.end_date)}
              </dd>
            </div>
            <div>
              <dt>Location</dt>
              <dd>{textValue(item.location)}</dd>
            </div>
            <div>
              <dt>Description</dt>
              <dd>{textValue(item.description)}</dd>
            </div>
          </dl>
        </article>
      ))}
    </div>
  );
}

function preferenceInputValue(value: string | number | null) {
  return value == null ? '' : String(value);
}

function PreferencesPanel({
  cv,
  onSaved,
}: {
  cv: UploadedCv;
  onSaved: (updatedCv: UploadedCv) => void;
}) {
  const navigate = useNavigate();
  const [preferredLocation, setPreferredLocation] = useState(
    cv.preferences.preferred_location ?? '',
  );
  const [salaryMin, setSalaryMin] = useState(preferenceInputValue(cv.preferences.salary_min));
  const [salaryMax, setSalaryMax] = useState(preferenceInputValue(cv.preferences.salary_max));
  const [workingArrangements, setWorkingArrangements] = useState<WorkingArrangement[]>(
    cv.preferences.working_arrangements,
  );
  const [industryKeyword, setIndustryKeyword] = useState(cv.preferences.industry_keyword ?? '');
  const [saving, setSaving] = useState(false);
  const [matchState, setMatchState] = useState<MatchState>('idle');
  const [matchProgress, setMatchProgress] = useState(0);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [matchError, setMatchError] = useState<string | null>(null);

  useEffect(() => {
    if (matchState !== 'matching') return undefined;

    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      const elapsedSeconds = (Date.now() - startedAt) / 1000;
      const nextProgress = Math.min((elapsedSeconds / EXPECTED_PROCESS_SECONDS) * 95, 95);
      setMatchProgress(nextProgress);
    }, 250);

    return () => window.clearInterval(timer);
  }, [matchState]);

  function toggleArrangement(arrangement: WorkingArrangement) {
    setWorkingArrangements((current) =>
      current.includes(arrangement)
        ? current.filter((item) => item !== arrangement)
        : [...current, arrangement],
    );
  }

  function salaryNumber(value: string) {
    if (!value.trim()) return null;
    return Number(value);
  }

  function preferencePayload() {
    const parsedSalaryMin = salaryNumber(salaryMin);
    const parsedSalaryMax = salaryNumber(salaryMax);

    if (
      parsedSalaryMin != null &&
      parsedSalaryMax != null &&
      parsedSalaryMin > parsedSalaryMax
    ) {
      setSaveError('Minimum salary must be less than maximum salary.');
      return null;
    }

    return {
      preferred_location: preferredLocation.trim() || null,
      salary_min: parsedSalaryMin,
      salary_max: parsedSalaryMax,
      working_arrangements: workingArrangements,
      industry_keyword: industryKeyword.trim() || null,
    };
  }

  async function persistPreferences() {
    const payload = preferencePayload();
    if (!payload) return null;

    const response = await fetch(`${API_BASE_URL}/cvs/${cv.id}/preferences`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const errorBody = await response.json().catch(() => null);
      throw new Error(errorBody?.detail ?? `Save failed with ${response.status}`);
    }

    return (await response.json()) as UploadedCv;
  }

  async function savePreferences() {
    setSaving(true);
    setSaveError(null);
    setSaveMessage(null);

    try {
      const updatedCv = await persistPreferences();
      if (!updatedCv) return;
      onSaved(updatedCv);
      setSaveMessage('Preferences saved. Matching can begin.');
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : 'Unable to save preferences');
    } finally {
      setSaving(false);
    }
  }

  async function beginMatch() {
    setMatchState('matching');
    setMatchProgress(3);
    setMatchError(null);
    setSaveError(null);
    setSaveMessage(null);

    try {
      const updatedCv = await persistPreferences();
      if (!updatedCv) {
        setMatchState('idle');
        setMatchProgress(0);
        return;
      }
      onSaved(updatedCv);

      const response = await fetch(`${API_BASE_URL}/cvs/${cv.id}/matches`, {
        method: 'POST',
      });

      if (!response.ok) {
        const errorBody = await response.json().catch(() => null);
        throw new Error(errorBody?.detail ?? `Match failed with ${response.status}`);
      }

      setMatchProgress(100);
      setMatchState('success');
      navigate(`/cvs/${cv.id}/matches`);
    } catch (error) {
      setMatchState('error');
      setMatchError(error instanceof Error ? error.message : 'Unable to run matching');
    }
  }

  const canBeginMatch =
    Boolean(preferredLocation.trim()) ||
    Boolean(industryKeyword.trim()) ||
    workingArrangements.length > 0 ||
    Boolean(salaryMin.trim()) ||
    Boolean(salaryMax.trim());

  return (
    <section className="detail-section preference-editor">
      <div className="preference-heading">
        <div>
          <p className="panel-label">User-confirmed inputs</p>
          <h3>Matching Preferences</h3>
        </div>
      </div>

      <label className="form-field">
        <span>Location</span>
        <input
          value={preferredLocation}
          onChange={(event) => setPreferredLocation(event.target.value)}
          placeholder="London, Manchester, Remote UK"
        />
      </label>

      <div className="salary-row">
        <label className="form-field">
          <span>Salary min</span>
          <input
            min="0"
            type="number"
            value={salaryMin}
            onChange={(event) => setSalaryMin(event.target.value)}
            placeholder="90000"
          />
        </label>
        <label className="form-field">
          <span>Salary max</span>
          <input
            min="0"
            type="number"
            value={salaryMax}
            onChange={(event) => setSalaryMax(event.target.value)}
            placeholder="140000"
          />
        </label>
      </div>

      <div className="form-field">
        <span>Working arrangement</span>
        <div className="segmented-control">
          {[
            ['on_site', 'On-site'],
            ['hybrid', 'Hybrid'],
            ['remote', 'Remote'],
          ].map(([value, label]) => (
            <button
              className={workingArrangements.includes(value as WorkingArrangement) ? 'active' : ''}
              key={value}
              type="button"
              onClick={() => toggleArrangement(value as WorkingArrangement)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <label className="form-field">
        <span>Industry or keyword</span>
        <input
          value={industryKeyword}
          onChange={(event) => setIndustryKeyword(event.target.value)}
          placeholder="fintech, healthcare, platform engineering"
        />
      </label>

      {saveError ? <p className="error-message">{saveError}</p> : null}
      {saveMessage ? <p className="success-message">{saveMessage}</p> : null}
      {matchError ? <p className="error-message">{matchError}</p> : null}

      <div className="preference-actions">
        <button className="secondary-button" type="button" onClick={savePreferences}>
          {saving ? <Loader2 className="spin" size={18} /> : <Save size={18} />}
          Save preferences
        </button>
        <button
          className="primary-button"
          type="button"
          disabled={!canBeginMatch || matchState === 'matching'}
          onClick={beginMatch}
        >
          {matchState === 'matching' ? <Loader2 className="spin" size={18} /> : <Search size={18} />}
          Begin Match
        </button>
      </div>

      {matchState === 'matching' || matchState === 'success' ? (
        <div className="match-progress-panel">
          <div className="progress-track" aria-label="CV matching progress">
            <div className="progress-bar" style={{ width: `${matchProgress}%` }} />
          </div>
          <div className="progress-meta">
            <span>{Math.round(matchProgress)}%</span>
            <span>Building retrieval candidates from the local corpus</span>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function CvDetailPage() {
  const { documentId } = useParams();
  const [cv, setCv] = useState<UploadedCv | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadCv() {
      try {
        setLoading(true);
        setError(null);
        const response = await fetch(`${API_BASE_URL}/cvs/${documentId}`);
        if (!response.ok) throw new Error(`CV request failed with ${response.status}`);
        setCv(await response.json());
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : 'Unable to load CV');
      } finally {
        setLoading(false);
      }
    }

    void loadCv();
  }, [documentId]);

  if (loading) {
    return (
      <main className="page-shell">
        <AppHeader />
        <div className="loading-state">
          <Loader2 className="spin" size={24} />
          Loading extracted CV
        </div>
      </main>
    );
  }

  if (error || !cv) {
    return (
      <main className="page-shell">
        <AppHeader />
        <Link className="back-link" to="/">
          <ArrowLeft size={18} /> Back
        </Link>
        <p className="error-message">{error ?? 'CV not found'}</p>
      </main>
    );
  }

  const candidateName = cv.structured.name ?? cv.original_filename ?? 'Extracted CV';

  return (
    <main className="page-shell">
      <AppHeader />
      <Link className="back-link" to="/">
        <ArrowLeft size={18} /> Back to upload
      </Link>

      <section className="cv-detail-hero">
        <div>
          <p className="section-kicker">Extracted profile</p>
          <h2>{candidateName}</h2>
          <p>{cv.structured.summary ?? 'No summary was extracted from this CV.'}</p>
        </div>
        <div className="cv-meta-card">
          <p className="panel-label">Extraction</p>
          <strong>{formatSeconds(cv.openrouter_duration_seconds)}</strong>
          <span>{cv.page_count} pages</span>
          <span>{formatBytes(cv.file_size_bytes)} KB</span>
          <span>{formatDate(cv.created_at)}</span>
        </div>
      </section>

      <section className="detail-grid">
        <div className="detail-main">
          <PreferencesPanel cv={cv} onSaved={setCv} />

          <section className="detail-section">
            <h3>Experience</h3>
            <TimelineList items={cv.structured.experience} emptyLabel="No experience extracted" />
          </section>

          <section className="detail-section">
            <h3>Education</h3>
            <TimelineList items={cv.structured.education} emptyLabel="No education extracted" />
          </section>

          <section className="detail-section">
            <h3>Plain Text</h3>
            <pre className="plain-text-block">{cv.plain_text}</pre>
          </section>
        </div>

        <aside className="detail-sidebar">
          <section className="detail-section">
            <h3>Contact</h3>
            <div className="detail-field-stack">
              <DetailField icon={<Mail size={18} />} label="Email" value={cv.structured.email} />
              <DetailField icon={<Phone size={18} />} label="Phone" value={cv.structured.phone} />
              <DetailField
                icon={<MapPin size={18} />}
                label="Location"
                value={cv.structured.location}
              />
            </div>
          </section>

          <section className="detail-section">
            <h3>Skills</h3>
            <ChipList items={cv.structured.skills} />
          </section>

          <section className="detail-section">
            <h3>Extracted Signals</h3>
            <p className="mini-heading">Roles</p>
            <ChipList items={cv.structured.preferred_roles} />
            <p className="mini-heading">Locations</p>
            <ChipList items={cv.structured.preferred_locations} />
            <p className="mini-heading">Salary</p>
            <p className="muted-text">{cv.structured.salary_expectation ?? 'Not listed'}</p>
          </section>

          <section className="detail-section">
            <h3>Links</h3>
            {cv.structured.links.length === 0 ? (
              <p className="muted-text">Not listed</p>
            ) : (
              <div className="link-list">
                {cv.structured.links.map((link) => (
                  <a key={link} href={link} target="_blank" rel="noreferrer">
                    <LinkIcon size={16} />
                    {link}
                  </a>
                ))}
              </div>
            )}
          </section>

          <section className="detail-section">
            <h3>Certifications</h3>
            <ChipList items={cv.structured.certifications} />
          </section>
        </aside>
      </section>
    </main>
  );
}

function MatchesPage() {
  const { documentId } = useParams();
  const [matchesResponse, setMatchesResponse] = useState<CvMatchesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const maxMatchScore = Math.max(
    ...(matchesResponse?.matches.map((match) => match.rrf_score) ?? [0]),
  );

  useEffect(() => {
    async function loadMatches() {
      try {
        setLoading(true);
        setError(null);
        const response = await fetch(`${API_BASE_URL}/cvs/${documentId}/matches`);
        if (!response.ok) {
          const errorBody = await response.json().catch(() => null);
          throw new Error(errorBody?.detail ?? `Matches request failed with ${response.status}`);
        }
        setMatchesResponse(await response.json());
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : 'Unable to load matches');
      } finally {
        setLoading(false);
      }
    }

    void loadMatches();
  }, [documentId]);

  return (
    <main className="page-shell">
      <AppHeader />
      <Link className="back-link" to={`/cvs/${documentId}`}>
        <ArrowLeft size={18} /> Back to CV
      </Link>

      <section className="matches-hero">
        <div>
          <p className="section-kicker">Retrieval candidates</p>
          <h2>Stored CV matches</h2>
          <p>Hybrid BM25 and dense embedding candidates. LLM fit scores are not included yet.</p>
        </div>
        {matchesResponse ? (
          <div className="cv-meta-card">
            <p className="panel-label">Run #{matchesResponse.run.id}</p>
            <strong>{matchesResponse.matches.length}</strong>
            <span>{matchesResponse.run.index_model ?? 'Model not recorded'}</span>
            <span>{formatDate(matchesResponse.run.finished_at)}</span>
            <span>Retrieval depth {matchesResponse.run.retrieve_count}</span>
          </div>
        ) : null}
      </section>

      {loading ? (
        <div className="loading-state">
          <Loader2 className="spin" size={24} />
          Loading retrieval candidates
        </div>
      ) : null}

      {error ? <p className="error-message">{error}</p> : null}

      {!loading && !error && matchesResponse?.matches.length === 0 ? (
        <section className="detail-section">
          <h3>No retrieval candidates</h3>
          <p className="muted-text">This run completed, but no jobs passed the preference filters.</p>
        </section>
      ) : null}

      {matchesResponse && matchesResponse.matches.length > 0 ? (
        <section className="matches-list">
          {matchesResponse.matches.map((match) => (
            <article className="match-row" key={match.id}>
              <div className="match-rank">#{match.rank}</div>
              <div className="match-body">
                <div className="match-title-row">
                  <div>
                    <h3>{match.job.title}</h3>
                    <p className="match-company">
                      {match.job.company?.display_name ?? 'Company not listed'}
                    </p>
                  </div>
                  <div className="match-card-actions">
                    <Link
                      className="dig-deeper-link"
                      to={`/cvs/${documentId}/matches/${matchesResponse.run.id}/${match.id}`}
                    >
                      Dig deeper <ArrowUpRight size={17} />
                    </Link>
                    {match.job.redirect_url ? (
                      <a
                        className="view-job-link"
                        href={match.job.redirect_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        View job <ArrowUpRight size={15} />
                      </a>
                    ) : null}
                  </div>
                </div>
                <div className="match-meta">
                  <span>{match.job.location?.display_name ?? 'Location not listed'}</span>
                  <span>{formatSalary(match.job)}</span>
                </div>
                <div className="match-keywords">
                  {jobKeywordTags(match.job).map((tag) => (
                    <span key={tag}>{tag}</span>
                  ))}
                </div>
                <div className="match-scores">
                  <span>DivLabScore {divLabScore(match.rrf_score, maxMatchScore)}/100</span>
                  <span>Keyword match #{match.bm25_rank ?? 'n/a'}</span>
                  <span>Meaning match #{match.dense_rank ?? 'n/a'}</span>
                </div>
              </div>
            </article>
          ))}
        </section>
      ) : null}
    </main>
  );
}

function AnalysisScore({
  label,
  value,
}: {
  label: string;
  value: number | null;
}) {
  return (
    <div className="analysis-score">
      <div>
        <span>{label}</span>
        <strong>{value == null ? 'n/a' : `${value}/10`}</strong>
      </div>
      <div className="score-track">
        <div style={{ width: `${scorePercent(value)}%` }} />
      </div>
    </div>
  );
}

function MatchAnalysisPage() {
  const { documentId, runId, matchId } = useParams();
  const [detail, setDetail] = useState<CvMatchDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [analysing, setAnalysing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!analysing) return undefined;

    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      const elapsedSeconds = (Date.now() - startedAt) / 1000;
      setProgress(Math.min((elapsedSeconds / EXPECTED_PROCESS_SECONDS) * 95, 95));
    }, 250);

    return () => window.clearInterval(timer);
  }, [analysing]);

  useEffect(() => {
    async function loadAndAnalyse() {
      try {
        setLoading(true);
        setError(null);
        const detailResponse = await fetch(
          `${API_BASE_URL}/cvs/${documentId}/matches/${runId}/${matchId}`,
        );
        if (!detailResponse.ok) {
          const errorBody = await detailResponse.json().catch(() => null);
          throw new Error(errorBody?.detail ?? `Match request failed with ${detailResponse.status}`);
        }

        const loadedDetail = (await detailResponse.json()) as CvMatchDetailResponse;
        setDetail(loadedDetail);

        if (loadedDetail.analysis?.status === 'success') return;

        setAnalysing(true);
        setProgress(3);
        const analysisResponse = await fetch(
          `${API_BASE_URL}/cvs/${documentId}/matches/${runId}/${matchId}/analysis`,
          { method: 'POST' },
        );
        if (!analysisResponse.ok) {
          const errorBody = await analysisResponse.json().catch(() => null);
          throw new Error(errorBody?.detail ?? `Analysis failed with ${analysisResponse.status}`);
        }

        setDetail((await analysisResponse.json()) as CvMatchDetailResponse);
        setProgress(100);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : 'Unable to load analysis');
      } finally {
        setLoading(false);
        setAnalysing(false);
      }
    }

    void loadAndAnalyse();
  }, [documentId, runId, matchId]);

  const analysis = detail?.analysis;

  return (
    <main className="page-shell">
      <AppHeader />
      <Link className="back-link" to={`/cvs/${documentId}/matches`}>
        <ArrowLeft size={18} /> Back to matches
      </Link>

      {loading && !detail ? (
        <div className="loading-state">
          <Loader2 className="spin" size={24} />
          Loading match detail
        </div>
      ) : null}

      {error ? <p className="error-message">{error}</p> : null}

      {detail ? (
        <>
          <section className="match-detail-hero">
            <div>
              <p className="section-kicker">Deep match analysis</p>
              <h2>{detail.job.title}</h2>
              <p className="match-company">{detail.job.company?.display_name ?? 'Company not listed'}</p>
              <div className="match-meta">
                <span>{detail.job.location?.display_name ?? 'Location not listed'}</span>
                <span>{formatSalary(detail.job)}</span>
                <span>{detail.job.category?.label ?? detail.job.category?.tag ?? 'Category not listed'}</span>
              </div>
            </div>
            <div className="cv-meta-card">
              <p className="panel-label">LLM fit</p>
              <strong>{analysis?.overall == null ? '...' : `${analysis.overall}/10`}</strong>
              <span>{analysis?.model ?? 'Analysis pending'}</span>
              <span>{analysis?.finished_at ? formatDate(analysis.finished_at) : 'Not stored yet'}</span>
              {detail.job.redirect_url ? (
                <a href={detail.job.redirect_url} target="_blank" rel="noreferrer">
                  View job <ArrowUpRight size={16} />
                </a>
              ) : null}
            </div>
          </section>

          {analysing ? (
            <section className="detail-section">
              <div className="loading-state">
                <Loader2 className="spin" size={24} />
                Running deeper LLM analysis
              </div>
              <div className="progress-track" aria-label="LLM analysis progress">
                <div className="progress-bar" style={{ width: `${progress}%` }} />
              </div>
              <div className="progress-meta">
                <span>{Math.round(progress)}%</span>
                <span>Generating and storing fit evidence</span>
              </div>
            </section>
          ) : null}

          {analysis?.status === 'success' ? (
            <section className="analysis-grid">
              <div className="detail-section">
                <h3>Verdict</h3>
                <p className="analysis-summary">{analysis.summary}</p>
                <div className="analysis-score-grid">
                  <AnalysisScore label="Seniority" value={analysis.seniority_fit} />
                  <AnalysisScore label="Technical overlap" value={analysis.tech_overlap} />
                  <AnalysisScore label="Domain" value={analysis.domain_fit} />
                  <AnalysisScore label="Responsibilities" value={analysis.responsibilities_fit} />
                  <AnalysisScore label="Location" value={analysis.location_fit} />
                </div>
              </div>

              <div className="detail-section">
                <h3>Strengths</h3>
                <ul className="analysis-list">
                  {analysis.strengths.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>

              <div className="detail-section">
                <h3>Concerns</h3>
                {analysis.concerns.length === 0 ? (
                  <p className="muted-text">No material concerns returned.</p>
                ) : (
                  <ul className="analysis-list">
                    {analysis.concerns.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                )}
              </div>
            </section>
          ) : null}

          <section className="detail-grid">
            <div className="detail-main">
              <section className="detail-section">
                <h3>Job Description</h3>
                <p className="job-description">{detail.job.description ?? 'No description stored.'}</p>
              </section>
            </div>
            <aside className="detail-sidebar">
              <section className="detail-section">
                <h3>Retrieved Match</h3>
                <div className="match-scores">
                  <span>Rank #{detail.match.rank}</span>
                  <span>Keyword match #{detail.match.bm25_rank ?? 'n/a'}</span>
                  <span>Meaning match #{detail.match.dense_rank ?? 'n/a'}</span>
                </div>
              </section>
              <section className="detail-section">
                <h3>Job Details</h3>
                <div className="job-facts">
                  <div>
                    <span>Adzuna ID</span>
                    <strong>{detail.job.adzuna_id}</strong>
                  </div>
                  <div>
                    <span>Contract</span>
                    <strong>{friendlyLabel(detail.job.contract_type) ?? 'Not listed'}</strong>
                  </div>
                  <div>
                    <span>Hours</span>
                    <strong>{friendlyLabel(detail.job.contract_time) ?? 'Not listed'}</strong>
                  </div>
                  <div>
                    <span>Salary estimate</span>
                    <strong>{detail.job.salary_is_predicted ? 'Predicted' : 'Employer listed'}</strong>
                  </div>
                  <div>
                    <span>Created</span>
                    <strong>{formatDate(detail.job.created_at)}</strong>
                  </div>
                  <div>
                    <span>Updated</span>
                    <strong>{formatDate(detail.job.updated_at)}</strong>
                  </div>
                </div>
              </section>
              <section className="detail-section">
                <h3>Job Tags</h3>
                <ChipList items={jobKeywordTags(detail.job)} />
              </section>
              <section className="detail-section">
                <details className="raw-json-details">
                  <summary>Raw provider payload</summary>
                  <pre>{rawJsonPreview(detail.job.raw_json)}</pre>
                </details>
              </section>
            </aside>
          </section>
        </>
      ) : null}
    </main>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/cvs/:documentId" element={<CvDetailPage />} />
        <Route path="/cvs/:documentId/matches" element={<MatchesPage />} />
        <Route path="/cvs/:documentId/matches/:runId/:matchId" element={<MatchAnalysisPage />} />
      </Routes>
    </BrowserRouter>
  );
}
