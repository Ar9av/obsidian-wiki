// Pure helpers, kept free of React so `node --test` can check them.

// Mirrors links._key: page ids keep Unicode; only case and spaces change.
export const slug = (s) => s.trim().replace(/\\+$/, '').replace(/\.md$/i, '').split('/').filter((p) => p && p !== '.').map((p) => p.trim().toLowerCase().replace(/ /g, '-')).join('/')

export function splitFrontmatter(text) {
  text = text.replace(/\r\n/g, '\n')
  const m = text.match(/^---\n([\s\S]*?)\n---\n?/)
  if (!m) return [[], text]
  const props = []
  for (const line of m[1].split('\n')) {
    const kv = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/)
    if (kv) props.push([kv[1], kv[2].replace(/^>-?$/, '')])
    else if (props.length && line.trim()) {
      const last = props[props.length - 1]
      last[1] = [last[1], line.trim().replace(/^- /, '')].filter(Boolean).join(last[1] && !line.trim().startsWith('-') ? ' ' : ', ')
    }
  }
  return [props, text.slice(m[0].length)]
}

const WIKILINK = /!?\[\[([^\]|#]+)(#[^\]|]*)?(?:\|([^\]]+))?\]\]/g
// Like Obsidian (and links.strip_code), a [[link]] inside code is literal text.
// `^[inferred]`-style provenance markers become #/prov/ links, drawn as quiet badges.
const linkify = (md) => md.replace(/\^\[([^\]]+)\]/g, '[$1](#/prov/)').replace(WIKILINK, (_, target, anchor, label) => `[${(label ?? target).replace(/[[\]]/g, '')}](#/wl/${encodeURIComponent(target.trim())})`)
export const withLinks = (md) => md.split(/(^ {0,3}(?:```|~~~)[\s\S]*?^ {0,3}(?:```|~~~)[^\n]*$|`[^`\n]+`)/m).map((part, i) => (i % 2 ? part : linkify(part))).join('')

export function parseLog(md) {
  const out = []
  for (const line of md.split('\n')) {
    const m = line.match(/^- \[([^\]]+)\]\s+(\S+)\s*(.*)$/)
    if (!m) continue
    const fields = {}
    for (const f of m[3].matchAll(/([\w-]+)=("([^"]*)"|\S+)/g)) fields[f[1]] = f[3] ?? f[2]
    out.push({ ts: m[1], verb: m[2], fields })
  }
  return out.sort((a, b) => b.ts.localeCompare(a.ts))
}

// --- Next actions ------------------------------------------------------------
// What the vault needs next, most useful first. Each action names how to resolve
// it: a wiki skill run as an agent job, a link to a view, or a git sync.
export function nextActions({ status, todos = [], lint = null }) {
  if (!status) return []
  const out = []
  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`
  if (!status.pages && !(status.raw_files ?? status.raw_count)) {
    out.push({ id: 'empty', title: 'The vault is empty', detail: 'Drop notes, links or files into the inbox, then ingest them.', go: '/inbox' })
  }
  if ((status.raw_files ?? status.raw_count)) {
    out.push({ id: 'ingest', title: `${plural((status.raw_files ?? status.raw_count), 'file')} waiting in _raw/`, detail: 'Ingest turns them into linked wiki pages.', job: 'ingest' })
  }
  const lost = (status.sources ?? []).filter((s) => s.missing_pages?.length)
  if (lost.length) {
    out.push({ id: 'lost', title: `${plural(lost.length, 'source')} lost pages`, detail: 'Pages they produced no longer exist. Re-ingest or prune them.', go: '/sources' })
  }
  if (status.staging_count) {
    out.push({ id: 'staging', title: `${plural(status.staging_count, 'staged write')} to review`, detail: 'Agent edits waiting for your approval.', go: '/staging' })
  }
  const findings = Object.entries(lint?.stats?.findings ?? {}).filter(([, n]) => n)
  if (findings.length) {
    const total = findings.reduce((a, [, n]) => a + n, 0)
    const top = findings.sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k, n]) => `${n} ${k.replace(/_/g, ' ')}`).join(', ')
    out.push({ id: 'lint', title: `${plural(total, 'lint finding')}`, detail: top, job: 'lint' })
  }
  const stale = todos.filter((t) => t.stale)
  if (stale.length) {
    out.push({ id: 'stale', title: `${plural(stale.length, 'stale thread')}`, detail: 'Close or drop the ones you are done with.', go: '/memory' })
  }
  if (status.git?.repo && status.git.dirty_count) {
    out.push({ id: 'sync', title: `${plural(status.git.dirty_count, 'uncommitted change')}`, detail: `Commit and push the vault (branch ${status.git.branch}).`, sync: true })
  }
  return out
}

// --- Connect an agent ------------------------------------------------------
// Ready-to-paste MCP configs for the machine serving the viewer. stdio launches
// `python -m obsidian_wiki mcp` with this server's own interpreter (it has the
// server extra, and GUI apps often lack `obsidian-wiki` on PATH); http points at
// this server's /mcp. A key is never embedded: configs read WIKI_API_KEY.
const shq = (s) => (/^[\w@%+=:,./-]+$/.test(s) ? s : `'${s.replace(/'/g, `'\\''`)}'`)
const json = (o) => JSON.stringify(o, null, 2)
const NAME = 'wiki-memory'

// Hosted Claude (claude.ai, and Desktop's Connectors) reaches a server from
// Anthropic's cloud, so a loopback or LAN address can't work there.
const isPublic = (url) => /^https:\/\//.test(url) && !/^https:\/\/(localhost|127\.|10\.|192\.168\.|\[::1\])/.test(url)

export function connectSnippets({ python, vault, url, keyRequired, oauth = false }, transport = 'stdio') {
  const args = ['-m', 'obsidian_wiki', 'mcp', '--vault', vault]
  const stdio = { command: python, args }
  const auth = (fmt) => (keyRequired ? { headers: { Authorization: `Bearer ${fmt}` } } : {})
  const http = transport === 'http'
  const servers = (entry) => json({ mcpServers: { [NAME]: entry } })
  return [
    {
      id: 'claude-code', label: 'Claude Code', where: 'Run in a terminal', lang: 'bash',
      code: http
        ? `claude mcp add --scope user --transport http ${NAME} ${shq(url)}${keyRequired ? ' \\\n  --header "Authorization: Bearer $WIKI_API_KEY"' : ''}`
        : `claude mcp add --scope user ${NAME} -- \\
  ${shq(python)} -m obsidian_wiki mcp \\
  --vault ${shq(vault)}`,
    },
    {
      id: 'codex', label: 'Codex', where: '~/.codex/config.toml', lang: 'toml',
      code: `[mcp_servers.${NAME}]\n` + (http
        ? `url = ${JSON.stringify(url)}${keyRequired ? '\nbearer_token_env_var = "WIKI_API_KEY"' : ''}`
        : `command = ${JSON.stringify(python)}\nargs = ${JSON.stringify(args)}`),
    },
    {
      id: 'cursor', label: 'Cursor', where: '~/.cursor/mcp.json (or .cursor/mcp.json in a project)', lang: 'json',
      code: servers(http ? { url, ...auth('${env:WIKI_API_KEY}') } : stdio),
    },
    // The config file only launches local processes; over HTTP, mcp-remote bridges
    // stdio to this server. The key goes in the bridge's env, never on its argv.
    {
      id: 'claude-desktop', label: 'Claude Desktop',
      where: 'Settings → Developer → Edit Config (claude_desktop_config.json)', lang: 'json',
      code: servers(http
        ? {
            command: 'npx',
            args: ['-y', 'mcp-remote', url, ...(keyRequired ? ['--header', 'Authorization:${WIKI_AUTH}'] : [])],
            ...(keyRequired ? { env: { WIKI_AUTH: 'Bearer <WIKI_API_KEY>' } } : {}),
          }
        : stdio),
      note: http
        ? `Bridges this server into Claude Desktop with mcp-remote (needs Node). Replace <WIKI_API_KEY> with your key.${isPublic(url) ? ' Or use the "claude.ai connector" tab instead: no Node, and it syncs to claude.ai and mobile.' : ''}`
        : undefined,
    },
    ...(http
      ? [{
          id: 'claude-connector', label: 'claude.ai connector',
          where: 'claude.ai or Claude Desktop → Settings → Connectors → Add custom connector', lang: 'text',
          code: oauth
            ? `Remote MCP server URL: ${url}\n\nNo header needed: Claude opens this server's sign-in page.\nEnter WIKI_API_KEY (read and write) or WIKI_READ_KEY (read-only).`
            : `Remote MCP server URL: ${url}${keyRequired ? '\nRequest header:  Authorization: Bearer <WIKI_API_KEY>' : ''}`,
          note: isPublic(url)
            ? 'Claude connects from Anthropic\'s cloud, so this works anywhere you use Claude, including mobile.'
            : 'Claude connects from Anthropic\'s cloud, so this needs a public https:// address (see docs/deployment.md#https). For a server only this machine can reach, use the Claude Desktop tab.',
        }]
      : []),
    {
      id: 'gemini', label: 'Gemini CLI', where: '~/.gemini/settings.json', lang: 'json',
      code: servers(http ? { httpUrl: url, ...auth('$WIKI_API_KEY') } : stdio),
    },
    {
      id: 'vscode', label: 'VS Code / Copilot', where: '.vscode/mcp.json', lang: 'json',
      code: json({
        ...(http && keyRequired ? { inputs: [{ type: 'promptString', id: 'wiki-key', description: 'WIKI_API_KEY', password: true }] } : {}),
        servers: { [NAME]: http ? { type: 'http', url, ...auth('${input:wiki-key}') } : { type: 'stdio', ...stdio } },
      }),
    },
    {
      id: 'windsurf', label: 'Windsurf', where: '~/.codeium/windsurf/mcp_config.json', lang: 'json',
      code: servers(http ? { serverUrl: url, ...auth('${env:WIKI_API_KEY}') } : stdio),
    },
    {
      id: 'other', label: 'Any MCP client', where: 'The mcpServers block most clients accept', lang: 'json',
      code: servers(http ? { type: 'http', url, ...auth('<WIKI_API_KEY>') } : stdio),
    },
  ]
}

// Instructions to paste into AGENTS.md / CLAUDE.md / a system prompt, so the agent
// actually uses the tools instead of just having them.
export const AGENT_INSTRUCTIONS = `## Memory (obsidian-wiki)

You have long-term memory through the \`wiki-memory\` MCP tools.

- At the start of a session, call \`memory_recap\` (pass \`project\` when working in a repo) and treat the result as background about me and my open work.
- Before answering anything about past work, decisions, or my notes, call \`memory_search\`, then \`memory_read\` the pages you need. Cite page paths.
- When a session produces a reusable finding (a fix, a gotcha, a decision and why), save it with \`memory_write\` using category \`_raw\`, then call \`memory_sync\`.
- Record stable facts about me with \`memory_profile\` (action \`set\`) only when I state them; track unfinished work with \`memory_todo\`.
- Never write secrets or credentials to memory.`
