export const LANGUAGE_SHORTCUT = "Tab";

export function isLanguageShortcut(event: KeyboardEvent): boolean {
  if (event.isComposing || event.keyCode === 229) return false;
  if (event.shiftKey || event.altKey || event.ctrlKey || event.metaKey) return false;
  if (event.key !== LANGUAGE_SHORTCUT && event.code !== LANGUAGE_SHORTCUT) return false;
  // Gecko can retarget content events at the browser element in chrome.
  const target = (event as KeyboardEvent & { originalTarget?: EventTarget }).originalTarget
    || event.composedPath?.()[0] || event.target;
  const element = target as HTMLElement | null;
  return !element?.isContentEditable && !element?.closest?.("input, textarea, select, [role='textbox']");
}
