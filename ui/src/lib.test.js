// npm test — node:test, no dependencies
import assert from 'node:assert/strict'
import test from 'node:test'
import { parseLog, slug, splitFrontmatter, withLinks } from './lib.js'

test('slug matches links._key, keeping Unicode', () => {
  assert.equal(slug('concepts/Café Ünïcode.md'), 'concepts/café-ünïcode')
  assert.equal(slug(' Spaced Page '), 'spaced-page')
  assert.equal(slug('./a//B.MD'), 'a/b')
})

test('wikilinks become internal links, but not inside code', () => {
  assert.equal(withLinks('see [[A b|alias]] and ![[img]]'), 'see [alias](#/wl/A%20b) and [img](#/wl/img)')
  assert.equal(withLinks('[[x#Heading]]'), '[x](#/wl/x)')
  assert.equal(withLinks('`[[y]]` [[z]]'), '`[[y]]` [z](#/wl/z)')
  assert.equal(withLinks('```\n[[c]]\n```\n[[d]]'), '```\n[[c]]\n```\n[d](#/wl/d)')
  assert.equal(withLinks('~~~py\n[[c]]\n~~~'), '~~~py\n[[c]]\n~~~')
  assert.equal(withLinks('a claim ^[inferred] `^[kept]`'), 'a claim [inferred](#/prov/) `^[kept]`')
})

test('frontmatter: scalars, folded text, lists, CRLF, none', () => {
  const [props, body] = splitFrontmatter('---\r\ntitle: T\r\nsummary: >-\r\n  one\r\n  two\r\ntags:\r\n  - a\r\n  - b\r\n---\r\n# Body')
  assert.deepEqual(props, [['title', 'T'], ['summary', 'one two'], ['tags', 'a, b']])
  assert.equal(body, '# Body')
  assert.deepEqual(splitFrontmatter('# no fm'), [[], '# no fm'])
})

test('log lines parse into newest-first entries with quoted fields', () => {
  const log = parseLog('## Log\n- [2026-01-01T00:00:00Z] INIT a=1\n\n- [2026-02-01T00:00:00Z] CAPTURE page="x y.md" title="T t"\nnot a line')
  assert.deepEqual(log.map((e) => e.verb), ['CAPTURE', 'INIT'])
  assert.deepEqual(log[0].fields, { page: 'x y.md', title: 'T t' })
  assert.deepEqual(log[1].fields, { a: '1' })
})

test('connect snippets: valid configs, quoted paths, no embedded key', async () => {
  const { connectSnippets } = await import('./lib.js')
  const env = { python: '/Users/a b/.venv/bin/python', vault: "/Users/a b/my 'vault'", url: 'http://127.0.0.1:3114/mcp/', keyRequired: true }
  for (const transport of ['stdio', 'http']) {
    const snippets = connectSnippets(env, transport)
    assert.equal(new Set(snippets.map((s) => s.id)).size, snippets.length)
    for (const s of snippets) {
      if (s.lang === 'json') JSON.parse(s.code)
      assert.ok(!s.code.includes('k123'))
    }
  }
  const stdio = Object.fromEntries(connectSnippets(env, 'stdio').map((s) => [s.id, s.code]))
  assert.deepEqual(JSON.parse(stdio.cursor).mcpServers['wiki-memory'], { command: env.python, args: ['-m', 'obsidian_wiki', 'mcp', '--vault', env.vault] })
  assert.equal(stdio['claude-code'], `claude mcp add --scope user wiki-memory -- \\\n  '/Users/a b/.venv/bin/python' -m obsidian_wiki mcp \\\n  --vault '/Users/a b/my '\\''vault'\\'''`)
  assert.match(stdio.codex, /^args = \["-m","obsidian_wiki","mcp","--vault","\/Users\/a b\/my 'vault'"\]$/m)
  const http = Object.fromEntries(connectSnippets(env, 'http').map((s) => [s.id, s.code]))
  assert.match(http['claude-code'], /--transport http wiki-memory http:\/\/127\.0\.0\.1:3114\/mcp\/ \\\n {2}--header "Authorization: Bearer \$WIKI_API_KEY"/)
  assert.match(http.codex, /bearer_token_env_var = "WIKI_API_KEY"/)
  assert.equal(JSON.parse(http.vscode).servers['wiki-memory'].headers.Authorization, 'Bearer ${input:wiki-key}')
  const open = Object.fromEntries(connectSnippets({ ...env, keyRequired: false }, 'http').map((s) => [s.id, s.code]))
  assert.ok(!open['claude-code'].includes('--header') && !JSON.parse(open.cursor).mcpServers['wiki-memory'].headers)
})
