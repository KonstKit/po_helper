# Onboarding Wizard Guide

## 🎯 Overview

Onboarding Wizard помогает новым пользователям быстро настроить PO Helper и начать работу с системой. Весь процесс занимает 5-10 минут и включает 6 шагов.

## 📋 Когда показывается онбординг

Wizard автоматически появляется при первом входе пользователя в систему (если `localStorage.getItem('onboarding_completed')` не установлен).

## 🚀 Шаги онбординга

### Step 1: Welcome & Use Case Selection

**Цель:** Понять, для чего пользователь хочет использовать систему

**Опции:**
- Track team velocity and sprint metrics
- Ensure requirements traceability
- Monitor code quality and test coverage
- All of the above (recommended) ← по умолчанию

**Логика:** Выбор влияет на рекомендации в финальном шаге

---

### Step 2: Jira Connection (Required)

**Цель:** Подключиться к Jira инстансу

**Поля:**
- Jira Base URL (например: `https://company.atlassian.net`)
- Email (Jira account email)
- API Token (генерируется на https://id.atlassian.com/manage-profile/security/api-tokens)

**Функции:**
- Кнопка "Test Connection" - проверяет подключение
- При успехе показывает количество найденных проектов
- Без успешного подключения нельзя продолжить

**Backend endpoint:** `POST /api/v1/integrations/jira/test`

---

### Step 3: Select Project

**Цель:** Выбрать первый проект для синхронизации

**Данные:** Список проектов получен из Step 2

**Отображение:**
- Название проекта
- Ключ проекта (например, WABA)
- Тип проекта

**Логика:** Выбранный проект будет синхронизирован первым в Step 5

---

### Step 4: Optional Integrations

**Цель:** Предложить настроить дополнительные интеграции

**Опции (чекбоксы):**
- ☑ Confluence - Link requirements to tasks
- ☐ GitHub - Track commits and PRs
- ☐ GitLab - Track commits and PRs
- ☐ TestRail - Import test cases

**Кнопки:**
- "Skip All" - пропустить все интеграции
- "Configure" - перейти к следующему шагу

**Примечание:** Все интеграции можно настроить позже в Settings

---

### Step 5: First Sync

**Цель:** Синхронизировать данные из выбранного проекта

**Процесс:**
1. Пользователь нажимает "Start Sync"
2. Показывается прогресс с real-time обновлениями:
   - ✓ Loaded N tasks from PROJECT_KEY
   - ✓ Loaded N sprints
   - ⏳ Analyzing velocity...
   - ⏳ Calculating metrics...
3. Progress bar показывает процент выполнения
4. После завершения автоматически переходит к Step 6

**Backend endpoint:** `POST /api/v1/jira/sync`

**Параметры:**
```json
{
  "project_key": "WABA"
}
```

**Ожидаемое время:** 1-2 минуты

---

### Step 6: Success & Next Steps

**Цель:** Показать результаты и рекомендовать следующие действия

**Отображение:**
- 🎉 Celebration icon
- Количество синхронизированных задач
- Количество спринтов
- Список того, что уже доступно

**Рекомендуемые следующие шаги:**
1. Map Jira custom fields for better analytics (Settings → Jira Fields)
2. Run traceability backfill (Traceability → Run Backfill)
3. Connect Git for commit tracking (Settings → GitHub/GitLab)

**Кнопки:**
- "Show Me Around" - интерактивный тур по приложению (будущая функция)
- "Go to Dashboard" - перейти на главный дашборд

---

## 💾 Хранение прогресса

### localStorage keys:

1. **`onboarding_progress`** - JSON объект с текущим состоянием:
```json
{
  "useCase": "all",
  "jiraUrl": "https://company.atlassian.net",
  "jiraEmail": "user@company.com",
  "jiraToken": "encrypted_token",
  "jiraProjects": [...],
  "selectedProjectKey": "WABA",
  "integrationsEnabled": {
    "confluence": false,
    "github": false,
    "gitlab": false,
    "testRail": false
  },
  "syncResults": {
    "tasks": 500,
    "sprints": 12,
    "complete": true
  }
}
```

2. **`onboarding_completed`** - флаг завершения (`"true"`)

### Логика восстановления:

- При открытии wizard загружает состояние из `onboarding_progress`
- Пользователь может продолжить с того места, где остановился
- После завершения `onboarding_progress` удаляется

---

## 🔄 Повторный запуск онбординга

Для тестирования или повторной настройки:

```javascript
// В браузерной консоли:
localStorage.removeItem('onboarding_completed');
localStorage.removeItem('onboarding_progress');
// Перезагрузить страницу
```

Или добавить кнопку "Reset Onboarding" в Settings (будущая функция).

---

## 🎨 Дизайн компоненты

### Используемые Material-UI компоненты:
- `Dialog` - основной контейнер wizard
- `Stepper` - индикатор прогресса (6 шагов)
- `Card` - для опций выбора
- `RadioGroup` / `Checkbox` - для выбора опций
- `LinearProgress` - для синхронизации
- `Alert` - для ошибок и успешных сообщений

### Цвета:
- Primary actions: `variant="contained"` (синий)
- Secondary actions: `variant="outlined"` (серый border)
- Success states: `color="success"` (зеленый)
- Error states: `severity="error"` (красный)

---

## 🧪 Тестирование

### Ручное тестирование:

1. Очистить localStorage
2. Залогиниться в систему
3. Проверить каждый шаг wizard
4. Убедиться, что данные сохраняются между шагами
5. Проверить синхронизацию
6. Убедиться, что после завершения wizard больше не показывается

### Unit тесты (TODO):

- Тест переходов между шагами
- Тест валидации на каждом шаге
- Тест сохранения/восстановления прогресса
- Тест API calls (mock)

---

## 🚀 Deployment

### Production настройки:

1. Убедиться, что backend endpoints доступны:
   - `/api/v1/integrations/jira/test`
   - `/api/v1/jira/sync`

2. Настроить CORS для cross-origin requests

3. Добавить error handling для:
   - Network failures
   - API timeouts
   - Invalid credentials

4. Добавить analytics tracking:
   - Onboarding start
   - Step completion
   - Onboarding completion
   - Drop-off points

---

## 📊 Success Metrics

После внедрения отслеживать:

- **Onboarding completion rate** (target: >80%)
- **Time to first sync** (target: <5 minutes)
- **Drop-off rate per step**
- **Users completing full setup** (target: >60%)

---

## 🔮 Future Enhancements

1. **Show Me Around** - интерактивный тур по dashboard
2. **Resume Setup** - кнопка в header для незавершенного онбординга
3. **Video tutorials** - встроенные видео на каждом шаге
4. **Smart defaults** - автоопределение настроек из Jira
5. **Multi-project setup** - выбор нескольких проектов сразу
6. **Email notifications** - уведомление после завершения синхронизации

---

## 📝 Changelog

**v1.0.0** (2025-10-01)
- Initial implementation
- 6-step wizard flow
- localStorage persistence
- Jira connection testing
- First project sync
- Success screen with recommendations
