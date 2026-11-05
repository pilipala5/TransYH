type Phase = "translation_worker" | "attachment_import" | "automatic_highlights" | "highlight_worker"
  | "highlight_install" | "attachment_save" | "reader_refresh" | "cleanup";

/** Numerical local lifecycle checkpoints expose waits after Python exits. */
export class TaskPerformance {
  private started = Date.now();
  private phaseStarted = this.started;
  private phase: Phase;
  private stages: { phase: Phase; milliseconds: number }[] = [];
  private status = "running";
  constructor(private directory: string, phase: Phase) { this.phase = phase; }

  async mark(phase: Phase): Promise<void> {
    const now = Date.now();
    this.stages.push({ phase: this.phase, milliseconds: now - this.phaseStarted });
    this.phase = phase; this.phaseStarted = now;
    await this.write();
  }
  async finish(status: "completed" | "failed"): Promise<void> {
    await this.mark("cleanup");
    this.status = status;
    await this.write();
  }
  async write(): Promise<void> {
    try {
      const now = Date.now();
      const record = { schema: 1, status: this.status, startedAt: this.started,
        checkedAt: now, elapsedMilliseconds: now - this.started,
        currentPhase: this.phase, phaseStartedAt: this.phaseStarted, stages: this.stages };
      const path = PathUtils.join(this.directory, "task-performance.json");
      await IOUtils.writeJSON(path, record, { tmpPath: path + ".tmp", permissions: 0o600 });
    } catch { /* Diagnostic storage failure must not fail a completed PDF task. */ }
  }
}
