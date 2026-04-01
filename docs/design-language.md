# OpenCode Orchestrator Design Language

This document defines the visual design language for the OpenCode Orchestrator UI. It covers all existing components and provides guidance for future elements.

## Design Philosophy

The UI follows a **utilitarian minimal** approach:
- Clean, distraction-free interface focused on function
- High contrast for readability
- Subtle interactions rather than flashy animations
- Consistent spacing and typography

## Color Palette

### Core Colors

| Token | Hex | Usage |
|-------|-----|-------|
| `--bg` | `#ffffff` | Page background |
| `--bg-secondary` | `#f5f5f5` | Cards, modals, secondary areas |
| `--bg-card` | `#ffffff` | Card backgrounds |
| `--text` | `#111111` | Primary text |
| `--text-muted` | `#666666` | Secondary text, labels |
| `--border` | `#dddddd` | Borders, dividers |
| `--accent` | `#333333` | Primary accent, focus states |
| `--accent-hover` | `#000000` | Hover states |

### Semantic Colors

| Token | Hex | Usage |
|-------|-----|-------|
| `--success` | `#2a2a2a` | Success states |
| `--warning` | `#555555` | Warning states |
| `--danger` | `#333333` | Danger/error states |

### Status Colors (Badges & Indicators)

| Status | Background | Text | Border |
|--------|------------|------|--------|
| Running | `#333333` | `#ffffff` | `#333333` |
| Completed | `#eeeeee` | `#333333` | `#cccccc` |
| Failed | `#333333` | `#ffffff` | `#333333` |
| Created | `#ffffff` | `#333333` | `#cccccc` |
| Available | `#333333` | `#ffffff` | `#333333` |
| Archived | `#666666` | `#ffffff` | `#666666` |

### Session Status Dots

| Status | Color |
|--------|-------|
| Spawned/Running | `#2a2a2a` |
| Stopping | `#555555` |
| Completed | `#666666` |
| Failed | `#333333` |

### Special Elements

| Element | Background | Text | Border |
|---------|------------|------|--------|
| Question box | `#fef9e7` | - | `#f1c40f` |
| Question type badge | `#f1c40f` | `#000000` | - |
| Question answered | `#e8f5e9` | - | `#4caf50` |
| Error message | `#fee` | `#500` | `#fcc` |

## Typography

### Font Stack

```css
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
```

### Sizes

| Element | Size | Weight |
|---------|------|--------|
| Page title (h1) | 1.5rem | 600 |
| Section title (h2) | 1.1rem | 600 |
| Section header (h3) | 1rem | 600 |
| Card title | 0.9rem | 500 |
| Body text | 0.95rem | 400 |
| Small/meta text | 0.85rem | 400 |
| Badge text | 0.75rem | 600 |
| Label text | 0.85rem | 400 |

### Line Heights

- Body: 1.6
- Headings: 1.3
- Inline elements: 1.4

## Spacing System

Base unit: 0.25rem (4px)

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | 0.25rem | Tight spacing |
| `--space-sm` | 0.5rem | Component internal |
| `--space-md` | 1rem | Standard gaps |
| `--space-lg` | 1.5rem | Section spacing |
| `--space-xl` | 2rem | Major sections |
| `--space-2xl` | 3rem | Page padding |

### Common Spacing Patterns

- Container padding: 2rem
- Card padding: 1.25rem
- Button padding: 0.5rem 1rem
- Form input padding: 0.6rem
- List item gap: 0.5rem
- Section margin: 1.5rem

## Components

### 1. Navbar

```html
<nav class="navbar">
    <div class="nav-brand">OpenCode Orchestrator</div>
    <div class="nav-links">
        <a href="/projects" class="nav-link">Projects</a>
        <a href="/settings" class="nav-link">Settings</a>
    </div>
</nav>
```

- Background: `--bg-secondary`
- Height: auto (padding 1rem 2rem)
- Border-bottom: 1px solid `--border`
- Brand: font-weight 700, font-size 1.1rem
- Links: gap 1.5rem, padding 0.4rem 0.8rem, border-radius 4px

### 2. Container

- Max-width: 1200px
- Margin: 0 auto
- Padding: 2rem

### 3. Page Header

```html
<div class="page-header">
    <h1>Page Title</h1>
    <div class="project-nav">
        <button class="btn btn-sm">Action</button>
    </div>
</div>
```

- Display: flex, justify-content space-between, align-items center
- Margin-bottom: 2rem
- Padding-bottom: 1rem
- Border-bottom: 1px solid `--border`

### 4. Buttons

| Class | Background | Text | Border | Hover |
|-------|------------|------|--------|-------|
| `.btn` | `--bg` | `--text` | `--border` | bg `--bg-secondary`, border `--accent` |
| `.btn-sm` | same | same | same | same |
| `.btn-primary` | same | same | same | same |
| `.btn-secondary` | same | same | same | same |
| `.btn-danger` | `#fee` | `#500` | `#fcc` | bg `#fdd`, border `#c00` |

**Properties:**
- Border-radius: 4px
- Font-size: 0.9rem (0.8rem for `.btn-sm`)
- Padding: 0.5rem 1rem (0.3rem 0.6rem for `.btn-sm`)
- Transition: all 0.2s

### 5. Badges

```html
<span class="badge badge-running">Running</span>
<span class="badge badge-completed">Completed</span>
<span class="badge badge-failed">Failed</span>
<span class="badge badge-created">Created</span>
```

- Display: inline-block
- Padding: 0.2rem 0.5rem
- Border-radius: 3px
- Font-size: 0.75rem
- Font-weight: 600
- Background: `--bg-secondary`
- Border: 1px solid `--border`

**Status variants:**
- `.badge-running`: dark background, light text
- `.badge-completed`: light background, dark text
- `.badge-failed`: dark background, light text
- `.badge-created`: light background, dark text
- `.badge-archived`: muted gray

### 6. Cards

#### Project Card

```html
<div class="project-card">
    <div class="project-header">
        <h3>Project Name</h3>
        <span class="badge badge-git">git</span>
    </div>
    <p class="project-path">/path/to/project</p>
    <p class="project-vcs">https://github.com/...</p>
    <div class="project-meta">
        <a href="/projects/1" class="btn btn-sm">Tasks</a>
        <button class="btn btn-sm">Action</button>
    </div>
</div>
```

#### Agent Card

```html
<div class="agent-card">
    <div class="agent-header">
        <h3>Agent Name</h3>
        <span class="badge badge-available">available</span>
    </div>
    <p class="agent-command">opencode --port 3000</p>
    <div class="agent-actions">
        <button class="btn btn-sm">Start</button>
        <button class="btn btn-sm">Test</button>
    </div>
</div>
```

#### Task Card

```html
<a href="/tasks/1" class="task-card task-card-link">
    <div class="task-title">Task Title</div>
    <div class="task-meta">Running...</div>
</a>
```

**Properties:**
- Background: `--bg-card`
- Border: 1px solid `--border`
- Border-radius: 6px (4px for task cards)
- Padding: 1.25rem

### 7. Task Board

```html
<div class="task-board">
    <div class="task-column">
        <h3>Running</h3>
        <!-- task cards -->
    </div>
    <div class="task-column">
        <h3>Completed</h3>
    </div>
    <div class="task-column">
        <h3>Failed</h3>
    </div>
</div>
```

- Grid: 5 columns (desktop), 3 (tablet), 1 (mobile)
- Gap: 1rem
- Column background: `--bg-secondary`
- Column border-radius: 6px
- Column padding: 1rem

### 8. Forms

#### Form Group

```html
<div class="form-group">
    <label for="input-id">Label</label>
    <input type="text" id="input-id" name="name">
</div>
```

- Label: display block, margin-bottom 0.3rem, color `--text-muted`, font-size 0.85rem
- Input: width 100%, padding 0.6rem, border 1px solid `--border`, border-radius 4px
- Focus: border-color `--accent`

#### Form Row (for inline forms)

```html
<div class="form-row">
    <input type="text" placeholder="Input 1">
    <input type="text" placeholder="Input 2">
    <button class="btn btn-primary">Submit</button>
</div>
```

- Display: flex, gap 0.5rem
- Input: flex 1 for stretch

#### Select Dropdown

```html
<select id="task-model">
    <option value="">Default</option>
</select>
```

- Same styling as inputs
- Min-width: 220px (for model selectors)

### 9. Modals

```html
<div class="modal-backdrop">
    <div class="modal">
        <h2>Modal Title</h2>
        <form>
            <!-- form content -->
            <div class="modal-actions">
                <button type="button" class="btn btn-secondary">Cancel</button>
                <button type="submit" class="btn btn-primary">Submit</button>
            </div>
        </form>
    </div>
</div>
```

**Modal Backdrop:**
- Position: fixed, inset 0
- Background: rgba(0,0,0,0.5)
- Display: flex, align-items center, justify-content center
- Z-index: 100

**Modal:**
- Background: `--bg`
- Border-radius: 8px
- Padding: 2rem
- Min-width: 400px, max-width: 90vw
- Border: 1px solid `--border`

**Modal Actions:**
- Display: flex, justify-content flex-end, gap 0.5rem, margin-top 1.5rem

### 10. Tabs

```html
<div class="tabs">
    <button :class="{ active: activeTab === 'tasks' }">Tasks</button>
    <button :class="{ active: activeTab === 'sessions' }">Sessions</button>
</div>
```

- Display: flex, gap 0
- Border-bottom: 1px solid `--border`
- Button: background none, border none, color `--text-muted`, padding 0.8rem 1.5rem
- Active: color `--text`, border-bottom 2px solid `--accent`

### 11. Session List

```html
<div class="session-list">
    <div class="session-row">
        <div class="session-status session-status-running"></div>
        <div class="session-info">
            <div class="session-title">Session ID</div>
            <div class="session-meta">Agent: agent-id | Status: running</div>
        </div>
    </div>
</div>
```

- Session row: display flex, align-items center, gap 1rem, background `--bg-secondary`, border-radius 4px, padding 0.75rem 1rem
- Status dot: 8px x 8px, border-radius 50%

### 12. Messages (Chat)

```html
<div class="messages-container">
    <div class="message message-user">
        <div class="message-role">user</div>
        <div class="message-content">Message content</div>
        <div class="message-time">10:30:45</div>
    </div>
    <div class="message message-assistant">
        <div class="message-role">assistant</div>
        <div class="message-content">Response</div>
    </div>
    <div class="message message-error">Error message</div>
    <div class="message message-system">System note</div>
</div>
```

**Properties:**
- Padding: 0.5rem 0.75rem
- Border-radius: 4px
- Font-size: 0.9rem

**Message variants:**
- `.message-user`: align-self flex-end, background `--bg-secondary`, border `--border`
- `.message-assistant`: align-self flex-start, background `--bg`, border `--border`
- `.message-error`: background `#fee`, color `#500`, border `#fcc`
- `.message-system`: align-self center, border dashed `--border`, italic, font-size 0.85rem

#### Message Send Interaction (polled threads)

For chat threads that refresh via polling/HTMX swaps:

- Do not insert optimistic user messages directly into persisted-looking history.
- Use a pending send affordance on the submit button (`Sending...`, disabled) while in-flight.
- Keep pending state until the submitted user text is present in the server-rendered thread (sqlite-confirmed).
- Use HTMX request synchronization (`hx-sync`) so polling does not clobber send flows.
- On request failure, restore button state immediately and keep history unchanged.

### 13. Questions

```html
<div class="question-box">
    <div class="question-header">
        <span class="question-type">clarification</span>
    </div>
    <div class="question-content">
        <pre>Question content</pre>
    </div>
    <div class="question-response">
        <input type="text" class="question-response-input" placeholder="Type response...">
        <button class="btn btn-primary btn-sm">Send</button>
    </div>
</div>
<div class="question-box question-answered">
    <!-- answered state -->
</div>
```

- Background: `#fef9e7`
- Border: 1px solid `#f1c40f`
- Border-radius: 6px
- Question type badge: background `#f1c40f`, color `#000`, font-size 0.75rem
- Answered state: background `#e8f5e9`, border `#4caf50`

### 14. Info Sections (Task Detail)

```html
<div class="info-section">
    <h3>Section Title</h3>
    <div class="info-row">
        <span class="info-label">Label</span>
        <p>Value</p>
    </div>
</div>
```

- Background: `--bg-secondary`
- Border-radius: 6px
- Padding: 1rem
- Border: 1px solid `--border`
- H3: font-size 0.9rem, margin-bottom 0.75rem, border-bottom 1px solid `--border`, padding-bottom 0.5rem
- Label: font-size 0.75rem, color `--text-muted`, text-transform uppercase, letter-spacing 0.5px

### 15. Empty States

```html
<p class="empty-state">No items to display</p>
```

- Color: `--text-muted`
- Text-align: center
- Padding: 3rem
- Border: 1px dashed `--border`
- Border-radius: 6px

### 16. Session Panel (Console)

```html
<div class="session-panel">
    <h3>Session Console</h3>
    <div class="messages-container">
        <!-- messages -->
    </div>
    <div class="message-form">
        <input type="text" class="message-input" placeholder="Send message...">
        <button class="btn btn-primary">Send</button>
    </div>
</div>
```

- Background: `--bg-secondary`
- Border-radius: 6px
- Padding: 1rem
- Height: 500px
- Flex column layout

### 17. Create Form

```html
<div class="create-form">
    <div class="form-row">
        <select>...</select>
        <input type="text" placeholder="Description">
        <button class="btn btn-primary">Create</button>
    </div>
</div>
```

- Background: `--bg-secondary`
- Border-radius: 6px
- Padding: 1rem
- Border: 1px solid `--border`

## Responsive Breakpoints

```css
@media (max-width: 900px) {
    .task-board {
        grid-template-columns: repeat(3, 1fr);
    }
}

@media (max-width: 600px) {
    .task-board {
        grid-template-columns: 1fr;
    }
    .navbar {
        flex-direction: column;
        gap: 1rem;
    }
    .container {
        padding: 1rem;
    }
}
```

| Breakpoint | Width | Adjustments |
|------------|-------|-------------|
| Desktop | > 900px | Full layout, 5 columns |
| Tablet | 600-900px | 3 columns |
| Mobile | < 600px | Single column, stacked navbar |

## Animation & Transitions

- Default transition: `all 0.2s`
- Hover states: subtle background/border color changes
- No animations on load (instant display)
- Focus states: border-color change to `--accent`

## Future UI Elements

### Suggested Components

When adding new UI elements, follow these patterns:

1. **Dropdown Menus**
   - Same styling as buttons
   - Position: relative with absolute positioning
   - Background: `--bg-card`, border: 1px solid `--border`
   - Border-radius: 4px
   - Box-shadow for elevation

2. **Toast Notifications**
   - Position: fixed, bottom-right
   - Background: `--bg-card`
   - Border: 1px solid `--border`
   - Border-radius: 6px
   - Padding: 1rem
   - Auto-dismiss after 5 seconds

3. **Data Tables**
   - Header: background `--bg-secondary`, font-weight 600
   - Rows: border-bottom 1px solid `--border`
   - Alternating backgrounds optional (use sparingly)
   - Hover: background `--bg-secondary`

4. **Progress Indicators**
   - Height: 4px
   - Background: `--bg-secondary`
   - Fill: `--accent`
   - Border-radius: 2px

5. **Tooltips**
   - Background: `--text` (dark)
   - Text: `--bg` (light)
   - Font-size: 0.75rem
   - Padding: 0.3rem 0.6rem
   - Border-radius: 3px
   - Position: absolute, z-index 50

6. **Loading States**
   - Skeleton screens with subtle pulse animation
   - Background: `--bg-secondary`
   - Border-radius: 4px

## Implementation Notes

- All components use CSS custom properties defined in `:root`
- No external CSS frameworks required
- Compatible with Alpine.js for reactivity
- HTMX-friendly (no conflicting classes)
- Accessibility: proper semantic HTML, focusable elements, sufficient contrast
