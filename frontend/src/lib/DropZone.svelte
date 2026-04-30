<script lang="ts">
	import { postUpload } from './api.js';
	import { appState } from './stores.svelte.js';
	import { subscribeToJob } from './eventSource.js';
	import { listUploads } from './api.js';

	let dragOver = $state(false);
	let uploading = $state(false);
	let uploadError = $state<string | null>(null);
	let unsubscribe: (() => void) | null = null;

	async function handleFile(file: File) {
		if (!file.type.startsWith('image/')) {
			uploadError = 'Please drop an image file.';
			return;
		}
		uploadError = null;
		uploading = true;
		appState.reset();

		try {
			const { job_id } = await postUpload(file);
			appState.currentJobId = job_id;
			unsubscribe?.();
			unsubscribe = subscribeToJob(job_id);

			// refresh history after a short delay so the new row is visible
			setTimeout(async () => {
				appState.history = await listUploads();
			}, 500);
		} catch (e) {
			uploadError = e instanceof Error ? e.message : String(e);
		} finally {
			uploading = false;
		}
	}

	function onDrop(e: DragEvent) {
		e.preventDefault();
		dragOver = false;
		const file = e.dataTransfer?.files[0];
		if (file) handleFile(file);
	}

	function onDragOver(e: DragEvent) {
		e.preventDefault();
		dragOver = true;
	}

	function onDragLeave() {
		dragOver = false;
	}

	function onPaste(e: ClipboardEvent) {
		const item = Array.from(e.clipboardData?.items ?? []).find((i) =>
			i.type.startsWith('image/')
		);
		if (item) {
			const file = item.getAsFile();
			if (file) handleFile(file);
		}
	}

	function onFileInput(e: Event) {
		const input = e.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		if (file) handleFile(file);
		input.value = '';
	}
</script>

<svelte:window onpaste={onPaste} />

<div
	class="drop-zone"
	class:drag-over={dragOver}
	class:uploading
	role="button"
	tabindex="0"
	aria-label="Drop or paste a screenshot"
	ondrop={onDrop}
	ondragover={onDragOver}
	ondragleave={onDragLeave}
	onkeydown={(e) => e.key === 'Enter' && document.getElementById('file-input')?.click()}
>
	{#if uploading}
		<span class="drop-label">Uploading…</span>
	{:else}
		<span class="drop-label">Drop a screenshot or paste an image</span>
		<span class="drop-hint">or <label class="file-link" for="file-input">browse files</label></span>
		<input
			id="file-input"
			type="file"
			accept="image/*"
			class="visually-hidden"
			onchange={onFileInput}
		/>
	{/if}
</div>

{#if uploadError}
	<p class="upload-error">{uploadError}</p>
{/if}
