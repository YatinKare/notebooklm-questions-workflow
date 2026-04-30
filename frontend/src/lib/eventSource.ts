import { API_BASE } from './api.js';
import { appState } from './stores.svelte.js';

const STAGE_LABELS: Record<string, string> = {
	extracting: 'extracting questions…',
	querying: 'querying NotebookLM…',
	parsing: 'parsing response…',
	verifying: 'verifying answers…',
	done: 'done',
	error: 'error'
};

export function subscribeToJob(jobId: string): () => void {
	let es: EventSource | null = null;
	let closed = false;
	let retries = 0;

	function connect() {
		es = new EventSource(`${API_BASE}/events/${jobId}`);

		es.addEventListener('stage_changed', (e) => {
			const data = JSON.parse((e as MessageEvent).data);
			appState.currentStage = STAGE_LABELS[data.state as string] ?? data.state;
		});

		es.addEventListener('question_extracted', (e) => {
			const q = JSON.parse((e as MessageEvent).data);
			appState.addOrUpdateCard({
				id: q.id as string,
				number: q.number as number,
				type: q.type,
				stem: q.stem as string,
				options: q.options as string[] | null
			});
		});

		es.addEventListener('question_completed', (e) => {
			const q = JSON.parse((e as MessageEvent).data);
			appState.completeCard(q.id as string, {
				correct_answer: q.correct_answer as string | string[] | null,
				reasoning: q.reasoning as string | null,
				confidence: q.confidence as 'high' | 'low' | null,
				flagged: q.flagged as boolean
			});
		});

		es.addEventListener('complete', () => {
			appState.currentStage = STAGE_LABELS['done'];
			closed = true;
			es?.close();
		});

		es.addEventListener('error', (e) => {
			// Named SSE event from server (not a network error)
			if (e instanceof MessageEvent) {
				const data = JSON.parse(e.data);
				appState.currentStage = 'error';
				appState.jobErrorMessage = data.message as string;
				appState.rawResponse = (data.raw_notebooklm_response as string | null) ?? null;
				closed = true;
				es?.close();
			}
		});

		es.onerror = () => {
			if (!closed && retries < 3) {
				retries++;
				es?.close();
				setTimeout(connect, 1500 * retries);
			} else if (!closed) {
				closed = true;
				es?.close();
			}
		};
	}

	connect();

	return () => {
		closed = true;
		es?.close();
	};
}
