<script lang="ts">
	import { onMount } from 'svelte';
	import DropZone from '$lib/DropZone.svelte';
	import QuestionCard from '$lib/QuestionCard.svelte';
	import { appState } from '$lib/stores.svelte.js';
	import { listUploads, getUpload } from '$lib/api.js';

	onMount(async () => {
		try {
			appState.history = await listUploads();
		} catch {
			// history load failure is non-fatal
		}
	});

	async function loadHistoryItem(id: string) {
		try {
			const upload = await getUpload(id);
			appState.loadFromUpload(upload);
		} catch (e) {
			console.error('Failed to load upload', e);
		}
	}

	function formatTime(iso: string): string {
		return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
	}
</script>

<svelte:head>
	<title>Screenshot → Answers</title>
</svelte:head>

<main>
	<h1>Screenshot → Answers</h1>

	<DropZone />

	{#if appState.currentJobId}
		<section class="section">
			<h2 class="section-title">Current upload</h2>

			{#if appState.currentStage === 'error' && appState.jobErrorMessage}
				<div class="job-error">
					<p class="error-msg">{appState.jobErrorMessage}</p>
					{#if appState.rawResponse}
						<details>
							<summary>show raw response</summary>
							<pre class="raw-response">{appState.rawResponse}</pre>
						</details>
					{/if}
				</div>
			{:else if appState.cards.length === 0}
				<p class="stage-label">{appState.currentStage || 'extracting questions…'}</p>
			{:else}
				{#if appState.currentStage && appState.currentStage !== 'done' && appState.currentStage !== 'error'}
					<p class="stage-label">{appState.currentStage}</p>
				{/if}
				<div class="card-list">
					{#each appState.cards as card (card.number)}
						<QuestionCard {card} stage={appState.currentStage} />
					{/each}
				</div>
			{/if}
		</section>
	{/if}

	{#if appState.history.length > 0}
		<section class="section">
			<h2 class="section-title">History</h2>
			<ul class="history-list">
				{#each appState.history as item (item.id)}
					<li>
						<button
							class="history-item"
							class:history-item--active={item.id === appState.currentJobId}
							onclick={() => loadHistoryItem(item.id)}
						>
							<span class="history-time">{formatTime(item.created_at)}</span>
							<span class="history-state" class:history-state--error={item.state === 'error'}>
								{item.state}
							</span>
							<span class="history-count">{item.question_count} Q{item.question_count !== 1 ? 's' : ''}</span>
						</button>
					</li>
				{/each}
			</ul>
		</section>
	{/if}
</main>
