export type Locale = 'en' | 'ru'

export const LOCALE_STORAGE_KEY = 'ai-team-locale'

export type MessageTree = Record<string, string | MessageTree>

function deepGet(tree: MessageTree, path: string): string | undefined {
  const parts = path.split('.')
  let cur: string | MessageTree | undefined = tree
  for (const p of parts) {
    if (cur === undefined || typeof cur === 'string') return undefined
    cur = cur[p]
  }
  return typeof cur === 'string' ? cur : undefined
}

const en: MessageTree = {
  common: {
    loading: 'Loading...',
    back: 'Back',
    continue: 'Continue',
    share: 'Share',
    settings: 'Settings',
    archive: 'Delete project',
    upload: 'Upload',
    active: 'Active',
    optional: '(optional)',
    language: 'Language',
    localeShortEn: 'EN',
    localeShortRu: 'RU',
  },
  time: {
    justNow: 'Just now',
    hoursAgo: '{{n}}h ago',
    daysAgo: '{{n}}d ago',
    dateLocale: 'en-US',
  },
  dashboard: {
    title: 'AI Team Platform',
    newProject: 'New Project',
    yourProjects: 'Your Projects',
    subtitle: 'Collaborate with AI agents on your projects',
    loadingProjects: 'Loading projects...',
    emptyTitle: 'No projects yet',
    emptySubtitle:
      'Create your first project to start collaborating with AI agents on your tasks.',
    createFirst: 'Create your first project',
    loadTimeout:
      'Loading took too long. Open http://127.0.0.1:3000 (not localhost), run the API on :8000 and check NEXT_PUBLIC_API_BASE_URL.',
    loadFailed: 'Failed to load projects',
  },
  projectCard: {
    messages: 'messages',
    messageCount: '{{count}} messages',
  },
  createProject: {
    title: 'Create New Project',
    backSr: 'Back to dashboard',
    stepInfo: 'Project Info',
    stepTeam: 'Select Team',
    stepDone: 'Complete',
    sectionInfoTitle: 'Project Information',
    sectionInfoSubtitle: 'Give your project a name and add any relevant files',
    nameLabel: 'Project Name',
    namePlaceholder: 'E.g., E-commerce Website',
    nameTooShort: 'Name must be at least 3 characters',
    descriptionLabel: 'Description',
    descriptionPlaceholder: 'Describe your project goals and requirements...',
    filesLabel: 'Files',
    filesHint: 'Upload briefs, mockups, or reference materials',
    sectionTeamTitle: 'Choose Your AI Agents',
    sectionTeamSubtitle: 'Select at least one agent to join your project team',
    demoBanner:
      'Layout mode: API is unavailable. Run the backend on port 8000 and refresh — real agents will appear; you cannot save a project with demo cards.',
    creating: 'Creating...',
    launch: 'Launch Project ({{count}} agent)',
    launch_plural: 'Launch Project ({{count}} agents)',
    successTitle: 'Project Created!',
    successSubtitle: 'Your project is ready. Redirecting to workspace...',
    redirecting: 'Redirecting...',
    toastCreated: 'Project created',
    toastCreateFailed: 'Failed to create project',
    toastAgentsFailed: 'Failed to load agents',
    toastDemoBlocked:
      'Start the backend (localhost:8000): demo agents are for UI preview only',
  },
  project: {
    backSr: 'Back to dashboard',
    moreAvatars: '+{{n}} more',
    chatEmptyTitle: 'Start the conversation',
    chatEmptySubtitle:
      'Send a message to your AI team. Use @mentions to address specific agents.',
    chatPlaceholder: 'Type a message... Use @Agent Name or @analyst to mention',
    attachSr: 'Attach file',
    mentionSr: 'Mention agent',
    sendSr: 'Send message',
    teamTitle: 'Team Members',
    teamCount_one: '{{count}} agent in this project',
    teamCount_other: '{{count}} agents in this project',
    addAgent: 'Add Agent',
    addAgentDialogTitle: 'Add Agent to Team',
    filesTitle: 'Project Files',
    filesCount_one: '{{count}} file uploaded',
    filesCount_other: '{{count}} files uploaded',
    uploadFiles: 'Upload Files',
    uploadDialogTitle: 'Upload Files',
    resultsTitle: 'Generated Results',
    resultsSubtitle: 'Outputs from your AI team organized by category',
    toastLoadFailed: 'Failed to load project',
    toastDiscussing: 'Agents are discussing...',
    toastDiscussTimeout: 'Discussion timed out — refresh the chat or try again',
    toastChatSyncFailed: 'Chat sync failed',
    toastSendFailed: 'Failed to send message',
    toastAddAgentFailed: 'Failed to add agent',
    toastRemoveAgentFailed: 'Failed to remove agent',
    toastUploadOk: 'Files uploaded',
    toastUploadFail: 'Failed to upload file',
    toastDeleteFail: 'Failed to delete file',
    toastProjectDeleted: 'Project deleted',
    toastProjectDeleteFailed: 'Failed to delete project',
    deleteDialogTitle: 'Delete this project?',
    deleteDialogDescription:
      'Are you sure? Deleted projects cannot be restored — chats, files, and results will no longer be available.',
    deleteDialogConfirm: 'Yes, delete',
    deleteDialogWorking: 'Deleting...',
    deleteDialogCancel: 'Cancel',
    removeAgentSr: 'Remove {{name}}',
    mentionListLabel: 'Agents in this project',
    mentionNoMatches: 'No matching agents',
    debateModeLabel: 'Discussion mode:',
    debateModeAuto: 'Auto',
    debateModeOff: 'Off',
    debateModeFast: 'Fast',
    debateModeStandard: 'Standard',
    debateModeDeep: 'Deep',
    debateStatusRound: 'Round {{cur}}/{{total}}',
    debateStatusSynthesizing: 'Synthesizing final answer...',
    debateStatusTimedOut: 'Discussion timed out',
    debateStatusFailed: 'Discussion failed',
    debateStatusCompleted: 'Discussion summary is ready',
    debateStatusCancelled: 'Discussion was cancelled by the user',
    debateCancelButton: 'Cancel',
    debateHelpTitle: 'Discussion details',
    debateHideDetails: 'Hide details',
    debateShowDetails: 'Show discussion details',
    debateMeta: 'Mode: {{mode}}, rounds: {{rounds}}, status: {{status}}',
    debateRoundLabel: 'Round {{round}} · {{status}}',
    toastDebateCancelled: 'Discussion cancelled',
    toastDebateCancelFailed: 'Failed to cancel discussion',
    chatFilesSelected: 'Selected files',
    chatRemoveFileSr: 'Remove file {{name}}',
    chatUploadingFiles: 'Uploading files...',
    chatAttachCount: '{{count}}',
    chatRoutingAnalyzing: 'Analyzing question...',
    routerAnalyzing: '🤖 Router analyzing…',
    routerChose: 'Router: {{flow}} → {{agents}}',
    routerReasonTitle: 'Router reasoning',
    routerUseManual: 'Use manual mode:',
    routerFlowOff: 'parallel answers',
    routerFlowSequential: 'sequential chain',
    routerFlowDebate: 'multi-round debate',
    chatSelectedAgents: 'Selected agents: {{names}}',
    chatSequentialSupplements: 'Supplements:',
  },
  tabs: {
    chat: 'Team Chat',
    agents: 'Agents',
    files: 'Files',
    results: 'Results',
    paperTrading: 'Paper Trading',
    tabsSr: 'Project tabs',
  },
  chat: {
    you: 'You',
    discussion: 'Discussion',
    agentFallback: 'Agent',
    typing: '{{name}} is typing...',
    thinking: 'Thinking...',
    emptyReplyWithError: 'No response received: {{error}}',
    emptyReplyNoContent: 'No response received (empty model output).',
    debateSummaryConsensus: 'Consensus',
    debateSummaryKeyArguments: 'Key arguments',
    debateSummaryOpenQuestions: 'Open questions / disagreements',
    debateSummaryConfidence: 'Confidence level',
    debateCancelledByUser: 'Discussion was cancelled by the user.',
    codeCopy: 'Copy',
    codeCopied: 'Copied',
    codeLoading: 'Rendering code...',
    mermaidError: 'Failed to render diagram',
    expand: 'Expand',
    collapse: 'Collapse',
    imageUnavailable: 'Image unavailable',
    closePreview: 'Close preview',
    downloadImage: 'Download image',
  },
  agentSelector: {
    selectSr: 'Select {{name}}',
  },
  results: {
    emptyTitle: 'No results yet',
    emptySubtitle:
      'Ask your team to start working on the project. Results will appear here as agents complete their tasks.',
    categoryArchitecture: 'Architecture',
    categoryDesign: 'Design',
    categoryCode: 'Code',
    categoryContent: 'Content',
    download: 'Download',
    downloadSr: 'Download {{title}}',
  },
  agentCards: {
    analyst:
      'Turns ideas into testable requirements. Surfaces risks and SLAs.',
    designer:
      'Designs flows and visual hierarchy. Focus on experience, not code.',
    frontend:
      'React/Next.js components with typing. Integrations, state, performance.',
    backend: 'Reliable APIs and data models. Contracts, migrations, observability.',
    frontend_dev:
      'React/Next.js components with typing. Integrations, state, performance.',
    backend_dev:
      'Reliable APIs and data models. Contracts, migrations, observability.',
    devops: 'Deployment automation and monitoring. Pipelines, IaC, security.',
    copywriter: 'UI and marketing copy. Brand tone and A/B variants.',
    arbiter: 'Resolves conflicts and synthesizes team outputs.',
    crypto_interpreter:
      'Translates crypto analysts output into simple step-by-step actions.',
    other: 'AI teammate.',
    fallback: 'AI teammate.',
  },
}

const ru: MessageTree = {
  common: {
    loading: 'Загрузка...',
    back: 'Назад',
    continue: 'Далее',
    share: 'Поделиться',
    settings: 'Настройки',
    archive: 'Удалить проект',
    upload: 'Загрузить',
    active: 'Активен',
    optional: '(необязательно)',
    language: 'Язык',
    localeShortEn: 'EN',
    localeShortRu: 'RU',
  },
  time: {
    justNow: 'Только что',
    hoursAgo: '{{n}} ч назад',
    daysAgo: '{{n}} дн назад',
    dateLocale: 'ru-RU',
  },
  dashboard: {
    title: 'AI Team Platform',
    newProject: 'Новый проект',
    yourProjects: 'Ваши проекты',
    subtitle: 'Совместная работа с AI-агентами над проектами',
    loadingProjects: 'Загрузка проектов...',
    emptyTitle: 'Пока нет проектов',
    emptySubtitle:
      'Создайте первый проект, чтобы начать работать с AI-командой над задачами.',
    createFirst: 'Создать первый проект',
    loadTimeout:
      'Загрузка затянулась. Откройте http://127.0.0.1:3000 (не localhost), запустите API на :8000 и проверьте NEXT_PUBLIC_API_BASE_URL.',
    loadFailed: 'Не удалось загрузить проекты',
  },
  projectCard: {
    messages: 'сообщений',
    messageCount: '{{count}} сообщ.',
  },
  createProject: {
    title: 'Новый проект',
    backSr: 'Назад к проектам',
    stepInfo: 'О проекте',
    stepTeam: 'Команда',
    stepDone: 'Готово',
    sectionInfoTitle: 'Информация о проекте',
    sectionInfoSubtitle: 'Укажите название и при необходимости прикрепите файлы',
    nameLabel: 'Название проекта',
    namePlaceholder: 'Например, Интернет-магазин',
    nameTooShort: 'Минимум 3 символа',
    descriptionLabel: 'Описание',
    descriptionPlaceholder: 'Цели проекта и требования...',
    filesLabel: 'Файлы',
    filesHint: 'Брифы, мокапы или референсы',
    sectionTeamTitle: 'Выбор AI-агентов',
    sectionTeamSubtitle: 'Выберите хотя бы одного агента в команду проекта',
    demoBanner:
      'Режим макета: API недоступен. Запустите бэкенд на порту 8000 и обновите страницу — появятся реальные агенты; создать проект с демо-карточками нельзя.',
    creating: 'Создание...',
    launch: 'Запустить проект ({{count}} агент)',
    launch_plural: 'Запустить проект ({{count}} агентов)',
    successTitle: 'Проект создан!',
    successSubtitle: 'Переходим в рабочую область...',
    redirecting: 'Переход...',
    toastCreated: 'Проект создан',
    toastCreateFailed: 'Не удалось создать проект',
    toastAgentsFailed: 'Не удалось загрузить агентов',
    toastDemoBlocked:
      'Запустите бэкенд (localhost:8000): демо-агенты только для просмотра UI',
  },
  project: {
    backSr: 'Назад к проектам',
    moreAvatars: '+ещё {{n}}',
    chatEmptyTitle: 'Начните диалог',
    chatEmptySubtitle:
      'Напишите AI-команде. Используйте @упоминания для конкретных агентов.',
    chatPlaceholder:
      'Сообщение... Укажите @имя агента или @analyst для обращения',
    attachSr: 'Прикрепить файл',
    mentionSr: 'Упоминание',
    sendSr: 'Отправить',
    teamTitle: 'Участники команды',
    teamCount_one: '{{count}} агент в проекте',
    teamCount_other: '{{count}} агентов в проекте',
    addAgent: 'Добавить агента',
    addAgentDialogTitle: 'Добавить агента в команду',
    filesTitle: 'Файлы проекта',
    filesCount_one: 'Загружен {{count}} файл',
    filesCount_other: 'Загружено файлов: {{count}}',
    uploadFiles: 'Загрузить файлы',
    uploadDialogTitle: 'Загрузка файлов',
    resultsTitle: 'Результаты',
    resultsSubtitle: 'Выводы AI-команды по категориям',
    toastLoadFailed: 'Не удалось загрузить проект',
    toastDiscussing: 'Агенты обсуждают...',
    toastDiscussTimeout:
      'Время ожидания истекло — обновите чат или попробуйте снова',
    toastChatSyncFailed: 'Ошибка синхронизации чата',
    toastSendFailed: 'Не удалось отправить сообщение',
    toastAddAgentFailed: 'Не удалось добавить агента',
    toastRemoveAgentFailed: 'Не удалось удалить агента',
    toastUploadOk: 'Файлы загружены',
    toastUploadFail: 'Не удалось загрузить файл',
    toastDeleteFail: 'Не удалось удалить файл',
    toastProjectDeleted: 'Проект удалён',
    toastProjectDeleteFailed: 'Не удалось удалить проект',
    deleteDialogTitle: 'Удалить проект?',
    deleteDialogDescription:
      'Вы уверены? Удалённые проекты нельзя восстановить — чаты, файлы и результаты станут недоступны.',
    deleteDialogConfirm: 'Да, удалить',
    deleteDialogWorking: 'Удаление...',
    deleteDialogCancel: 'Отмена',
    removeAgentSr: 'Удалить {{name}} из команды',
    mentionListLabel: 'Агенты проекта',
    mentionNoMatches: 'Нет совпадений',
    debateModeLabel: 'Режим дискуссии:',
    debateModeAuto: 'Авто',
    debateModeOff: 'Выкл',
    debateModeFast: 'Быстрый',
    debateModeStandard: 'Стандарт',
    debateModeDeep: 'Глубокий',
    debateStatusRound: 'Раунд {{cur}}/{{total}}',
    debateStatusSynthesizing: 'Синтезируем итог...',
    debateStatusTimedOut: 'Дискуссия прервана по таймауту',
    debateStatusFailed: 'Дискуссия завершилась с ошибкой',
    debateStatusCompleted: 'Итог дискуссии готов',
    debateStatusCancelled: 'Дискуссия отменена пользователем',
    debateCancelButton: 'Отменить',
    debateHelpTitle: 'Справка по дискуссии',
    debateHideDetails: 'Скрыть детали',
    debateShowDetails: 'Раскрыть детали дискуссии',
    debateMeta: 'Режим: {{mode}}, раундов: {{rounds}}, статус: {{status}}',
    debateRoundLabel: 'Раунд {{round}} · {{status}}',
    toastDebateCancelled: 'Дискуссия отменена',
    toastDebateCancelFailed: 'Не удалось отменить дискуссию',
    chatFilesSelected: 'Выбранные файлы',
    chatRemoveFileSr: 'Убрать файл {{name}}',
    chatUploadingFiles: 'Загружаем файлы...',
    chatAttachCount: '{{count}}',
    chatRoutingAnalyzing: 'Анализирую вопрос...',
    routerAnalyzing: '🤖 Router анализирует…',
    routerChose: 'Router: {{flow}} → {{agents}}',
    routerReasonTitle: 'Обоснование Router',
    routerUseManual: 'Зафиксировать режим:',
    routerFlowOff: 'параллельные ответы',
    routerFlowSequential: 'цепочка по очереди',
    routerFlowDebate: 'многораундовая дискуссия',
    chatSelectedAgents: 'Выбраны агенты: {{names}}',
    chatSequentialSupplements: 'Дополняет:',
  },
  tabs: {
    chat: 'Чат команды',
    agents: 'Агенты',
    files: 'Файлы',
    results: 'Результаты',
    paperTrading: 'Paper Trading',
    tabsSr: 'Вкладки проекта',
  },
  chat: {
    you: 'Вы',
    discussion: 'Обсуждение',
    agentFallback: 'Агент',
    typing: '{{name}} печатает...',
    thinking: 'Думает...',
    emptyReplyWithError: 'Ответ не получен: {{error}}',
    emptyReplyNoContent: 'Ответ не получен (пустой результат модели).',
    debateSummaryConsensus: 'Итог / Консенсус',
    debateSummaryKeyArguments: 'Ключевые аргументы',
    debateSummaryOpenQuestions: 'Открытые вопросы / Разногласия',
    debateSummaryConfidence: 'Уровень уверенности',
    debateCancelledByUser: 'Дискуссия отменена пользователем.',
    codeCopy: 'Копировать',
    codeCopied: 'Скопировано',
    codeLoading: 'Рендер кода...',
    mermaidError: 'Не удалось отрисовать схему',
    expand: 'Развернуть',
    collapse: 'Свернуть',
    imageUnavailable: 'Изображение недоступно',
    closePreview: 'Закрыть предпросмотр',
    downloadImage: 'Скачать изображение',
  },
  agentSelector: {
    selectSr: 'Выбрать {{name}}',
  },
  results: {
    emptyTitle: 'Пока нет результатов',
    emptySubtitle:
      'Когда агенты начнут работу, результаты появятся здесь.',
    categoryArchitecture: 'Архитектура',
    categoryDesign: 'Дизайн',
    categoryCode: 'Код',
    categoryContent: 'Контент',
    download: 'Скачать',
    downloadSr: 'Скачать {{title}}',
  },
  agentCards: {
    analyst:
      'Превращает идеи в тестируемые требования. Выявляет риски и SLA.',
    designer:
      'Проектирует сценарии и визуальную иерархию. Фокус на опыте, не коде.',
    frontend:
      'React/Next.js компоненты с типизацией. Интеграции, состояния, оптимизация.',
    backend:
      'Надёжные API и модели данных. Контракты, миграции, наблюдаемость.',
    frontend_dev:
      'React/Next.js компоненты с типизацией. Интеграции, состояния, оптимизация.',
    backend_dev:
      'Надёжные API и модели данных. Контракты, миграции, наблюдаемость.',
    devops:
      'Автоматизация деплоя и мониторинга. Пайплайны, IaC, безопасность.',
    copywriter:
      'Тексты интерфейсов и маркетинг. Адаптация под бренд и A/B-тесты.',
    arbiter: 'Синтезирует ответы команды и разрешает споры.',
    crypto_interpreter:
      'Переводит выводы крипто-аналитиков в простые пошаговые действия.',
    other: 'Участник AI-команды.',
    fallback: 'Участник AI-команды.',
  },
}

export const messages: Record<Locale, MessageTree> = { en, ru }

export function translate(locale: Locale, key: string): string {
  const primary = deepGet(messages[locale], key)
  if (primary !== undefined) return primary
  const fallback = deepGet(messages.en, key)
  return fallback ?? key
}

export function applyParams(str: string, params?: Record<string, string | number>): string {
  if (!params) return str
  let out = str
  for (const [k, v] of Object.entries(params)) {
    out = out.replaceAll(`{{${k}}}`, String(v))
  }
  return out
}

/** Язык браузера: только ru → ru, иначе en */
export function localeFromNavigator(): Locale {
  if (typeof navigator === 'undefined') return 'en'
  const lang = navigator.language?.toLowerCase() ?? ''
  return lang.startsWith('ru') ? 'ru' : 'en'
}
