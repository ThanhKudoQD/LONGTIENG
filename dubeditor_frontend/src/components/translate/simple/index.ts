// ─── Public API của Simple Translator v3 ──────────────────────────────────
// Import duy nhất ở App.tsx:
//   import TranslatePageSimple from './components/translate/simple'

export { default } from './TranslatePageSimple'
export { default as TranslatePageSimple } from './TranslatePageSimple'
export { default as ConfigPanel, defaultSimpleConfig, loadSimpleConfig, saveSimpleConfig } from './ConfigPanel'
export { MODELS, PROVIDER_LABELS, DEFAULT_TASK_MODELS } from './modelCatalog'

// API client
export {
  bibleApi, batchesApi, filterApi, reviewApi, issuesApi, configApi,
} from './simpleApi'

// WS hook
export { useSimpleWebSocket, type SimpleEvent, type SimpleWebSocketHandlers } from './hooks/useSimpleWebSocket'

// Re-export types
export type {
  SimpleTab, RunStatus,
  BibleMode, BiblePart, BibleMerge, BibleState,
  ConcurrencyMode, BatchInfo, TranslateState,
  ErrorType, ErrorSeverity, SubtitleError, FilterStats,
  ReviewSubMode, ContextLine, ReviewGroup, ReviewState,
  IssueStatus, SubtitleIssue, IssuesStats,
  Provider, ProviderApiKeys, TaskKey, SimpleConfig,
  ModelOption,
} from './types'
