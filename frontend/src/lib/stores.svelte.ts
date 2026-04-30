import type { QuestionType, Upload, UploadSummary } from './api.js';

export interface CardState {
	id?: string;
	number: number;
	type?: QuestionType;
	stem?: string;
	options?: string[] | null;
	correct_answer?: string | string[] | null;
	reasoning?: string | null;
	confidence?: 'high' | 'low' | null;
	flagged?: boolean;
	status: 'pending' | 'done' | 'error';
}

class AppState {
	currentJobId = $state<string | null>(null);
	currentStage = $state<string>('');
	cards = $state<CardState[]>([]);
	history = $state<UploadSummary[]>([]);
	jobErrorMessage = $state<string | null>(null);
	rawResponse = $state<string | null>(null);

	reset() {
		this.cards = [];
		this.currentStage = '';
		this.jobErrorMessage = null;
		this.rawResponse = null;
	}

	addOrUpdateCard(partial: Omit<CardState, 'status'> & { status?: CardState['status'] }) {
		const idx = this.cards.findIndex((c) => c.number === partial.number);
		if (idx >= 0) {
			this.cards[idx] = { ...this.cards[idx], ...partial };
		} else {
			const sorted = [...this.cards, { status: 'pending' as const, ...partial }];
			sorted.sort((a, b) => a.number - b.number);
			this.cards = sorted;
		}
	}

	completeCard(id: string, updates: Partial<CardState>) {
		this.cards = this.cards.map((c) =>
			c.id === id ? { ...c, ...updates, status: 'done' as const } : c
		);
	}

	loadFromUpload(upload: Upload) {
		this.currentJobId = upload.id;
		this.currentStage = upload.state;
		this.jobErrorMessage = upload.error_message;
		this.rawResponse = upload.raw_notebooklm_response;
		this.cards = upload.questions
			.map((q) => ({
				id: q.id,
				number: q.number,
				type: q.type,
				stem: q.stem,
				options: q.options,
				correct_answer: q.correct_answer,
				reasoning: q.reasoning,
				confidence: q.confidence,
				flagged: q.flagged,
				status: (q.correct_answer != null ? 'done' : 'pending') as CardState['status']
			}))
			.sort((a, b) => a.number - b.number);
	}
}

export const appState = new AppState();
