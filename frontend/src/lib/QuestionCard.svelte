<script lang="ts">
	import type { CardState } from './stores.svelte.js';

	interface Props {
		card: CardState;
		stage: string;
	}

	let { card, stage }: Props = $props();

	let expanded = $state(false);

	function toggleExpand() {
		if (card.status === 'done') expanded = !expanded;
	}

	function truncate(text: string, max = 60): string {
		return text.length > max ? text.slice(0, max) + '…' : text;
	}

	function formatAnswer(answer: string | string[] | null | undefined): string {
		if (answer == null) return '';
		if (Array.isArray(answer)) return answer.join(', ');
		return answer;
	}

	function isCorrect(option: string, answer: string | string[] | null | undefined): boolean {
		if (answer == null) return false;
		const optionLetter = option.match(/^([A-Za-z])[).\s]/)?.[1]?.toUpperCase();
		if (Array.isArray(answer)) {
			return answer.some((a) => a.toUpperCase() === optionLetter || option.includes(a));
		}
		return (
			answer.toUpperCase() === optionLetter ||
			option.toLowerCase().includes(answer.toLowerCase())
		);
	}

</script>

<div
	class="card"
	class:card--pending={card.status === 'pending'}
	class:card--done={card.status === 'done'}
	class:card--error={card.status === 'error'}
	class:card--flagged={card.flagged && card.confidence === 'low'}
>
	<!-- Header row -->
	<button class="card-header" onclick={toggleExpand} disabled={card.status !== 'done'}>
		<span class="card-label">
			Q{card.number}
			{#if card.type}<span class="card-type">({card.type})</span>{/if}
		</span>

		{#if card.status === 'pending'}
			{#if card.stem}
				<span class="card-stem">{truncate(card.stem)}</span>
				<span class="card-stage">{stage || 'waiting…'}</span>
			{:else}
				<span class="card-stage">{stage || 'waiting…'}</span>
			{/if}
			<span class="spinner" aria-label="processing"></span>
		{:else if card.status === 'done'}
			<span class="card-stem">{truncate(card.stem ?? '')}</span>
			<span class="card-answer">
				{#if card.type === 'TF'}
					<span class="answer-tf">{formatAnswer(card.correct_answer)}</span>
				{:else}
					→ <strong>{formatAnswer(card.correct_answer)}</strong>
				{/if}
			</span>
			{#if card.confidence === 'low' || card.flagged}
				<span class="badge badge--amber">low confidence</span>
			{/if}
			<span class="expand-icon" aria-hidden="true">{expanded ? '▴' : '▾'}</span>
		{/if}
	</button>

	<!-- Expanded body -->
	{#if expanded && card.status === 'done'}
		<div class="card-body">
			<p class="card-full-stem">{card.stem}</p>

			{#if card.options && card.options.length > 0}
				<ul class="options-list">
					{#each card.options as option}
						<li class="option" class:option--correct={isCorrect(option, card.correct_answer)}>
							{option}
						</li>
					{/each}
				</ul>
			{/if}

			{#if card.reasoning}
				<p class="reasoning">{card.reasoning}</p>
			{/if}

			{#if card.confidence === 'low' || card.flagged}
				<span class="badge badge--amber">low confidence — answer may not be source-grounded</span>
			{/if}
		</div>
	{/if}

	<!-- Error state at job level shown inline if this is an error card placeholder -->
	{#if card.status === 'error'}
		<div class="card-body">
			<p class="error-msg">{card.stem ?? 'An error occurred.'}</p>
		</div>
	{/if}
</div>
