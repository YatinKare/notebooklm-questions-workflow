import { PUBLIC_API_BASE } from '$env/static/public';

export const API_BASE = PUBLIC_API_BASE || 'http://localhost:8080';

export type QuestionType =
	| 'TF'
	| 'MCQ'
	| 'SELECT_MULTIPLE'
	| 'MATCHING'
	| 'SHORT_ANSWER'
	| 'SHORT_ANSWER_MATH'
	| 'LONG_ANSWER';

export interface Question {
	id: string;
	upload_id?: string;
	number: number;
	type: QuestionType;
	stem: string;
	options: string[] | null;
	correct_answer: string | string[] | null;
	reasoning: string | null;
	confidence: 'high' | 'low' | null;
	flagged: boolean;
}

export interface Upload {
	id: string;
	created_at: string;
	state: string;
	error_message: string | null;
	raw_notebooklm_response: string | null;
	questions: Question[];
}

export interface UploadSummary {
	id: string;
	created_at: string;
	state: string;
	question_count: number;
}

export async function postUpload(file: File): Promise<{ job_id: string }> {
	const form = new FormData();
	form.append('file', file);
	const res = await fetch(`${API_BASE}/uploads`, { method: 'POST', body: form });
	if (!res.ok) {
		const text = await res.text().catch(() => res.statusText);
		throw new Error(`Upload failed (${res.status}): ${text}`);
	}
	return res.json();
}

export async function listUploads(): Promise<UploadSummary[]> {
	const res = await fetch(`${API_BASE}/uploads`);
	if (!res.ok) throw new Error(`Failed to load history: ${res.status}`);
	return res.json();
}

export async function getUpload(jobId: string): Promise<Upload> {
	const res = await fetch(`${API_BASE}/uploads/${jobId}`);
	if (!res.ok) throw new Error(`Failed to load upload: ${res.status}`);
	return res.json();
}
