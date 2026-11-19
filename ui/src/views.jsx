import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Badge, Box, Button, Card, CardBody, CardHeader, Code, Divider, Flex, HStack, Heading, Input, Link, SimpleGrid, Skeleton,
  Stack, Stat, StatHelpText, StatLabel, StatNumber, Tab, TabList, TabPanel, TabPanels, Table, TableContainer, Tabs, Tag, Tbody, Td, Text, Th, Thead, Tr, Wrap,
  useBreakpointValue, useClipboard,
  useColorModeValue, useToken,
} from '@chakra-ui/react'
import { EmptyState, Property, PropertyList } from '@saas-ui/react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import ForceGraph2D from 'react-force-graph-2d'
import { Check, Copy, ExternalLink } from 'lucide-react'
import { api, go, useVault } from './main.jsx'
import { AGENT_INSTRUCTIONS, connectSnippets, parseLog, splitFrontmatter, withLinks } from './lib.js'

// --- building blocks -------------------------------------------------------
const pageHref = (path) => `#/page/${encodeURIComponent(path)}`
const titleOf = (path) => path.split('/').pop().replace(/\.md$/, '').replace(/[-_]/g, ' ')
// The page's frontmatter title when the graph has it, else a name from the filename.
const nameOf = (index, path) => index?.byPath.get(path)?.title || titleOf(path)

function Header({ title, description, children }) {
  return (
    <Flex px={{ base: 5, md: 8 }} pt="6" pb="4" align="end" gap="4" wrap="wrap">
      <Box flex="1" minW="0">
        <Heading size="md">{title}</Heading>
        {description && <Text color="muted" fontSize="sm" mt="1">{description}</Text>}
      </Box>
      {children}
    </Flex>
  )
}
const Body = (props) => <Box px={{ base: 5, md: 8 }} pb="10" {...props} />

function Section({ title, children, ...rest }) {
  return (
    <Card variant="outline" {...rest}>
      {title && <CardHeader pb="0"><Heading size="xs" textTransform="uppercase" color="muted" letterSpacing="wide">{title}</Heading></CardHeader>}
      <CardBody>{children}</CardBody>
    </Card>
  )
}

function useFetch(path, deps = []) {
  const [state, setState] = useState({ data: null, error: null })
  useEffect(() => {
    let live = true
    setState({ data: null, error: null })
    if (!path) return
    api.get(path).then((data) => live && setState({ data, error: null })).catch((e) => live && setState({ data: null, error: e.message }))
    return () => { live = false }
  }, [path, ...deps])
  return state
}

const Loading = () => <Stack px="8">{[0, 1, 2].map((i) => <Skeleton key={i} h="6" />)}</Stack>
export const ErrorState = ({ message }) => <EmptyState colorScheme="red" title="Couldn't load this" description={message} py="16" />
export const NotFound = () => <EmptyState title="Nothing here" description="That view doesn't exist." py="16" />

function DataTable({ head, rows, empty = 'Nothing to show.' }) {
  // Phones get one card per row instead of a table that scrolls sideways.
  const stacked = useBreakpointValue({ base: true, md: false }, { ssr: false })
  if (!rows.length) return <Text color="muted" fontSize="sm">{empty}</Text>
  if (stacked) {
    return (
      <Stack spacing="2">{rows.map((r, i) => (
        <Stack key={i} spacing="1.5" borderWidth="1px" borderRadius="md" p="3">{r.map((c, j) => (c == null || c === false || c === '') ? null : (
          <Flex key={j} gap="3" align="baseline" fontSize="sm">
            {head[j] && <Text w="20" flexShrink="0" color="muted" fontSize="xs" textTransform="uppercase" letterSpacing="wide">{head[j]}</Text>}
            <Box flex="1" minW="0" wordBreak="break-word">{c}</Box>
          </Flex>
        ))}</Stack>
      ))}</Stack>
    )
  }
  return (
    <TableContainer>
      <Table size="sm">
        <Thead><Tr>{head.map((h) => <Th key={h}>{h}</Th>)}</Tr></Thead>
        <Tbody>{rows.map((r, i) => <Tr key={i}>{r.map((c, j) => <Td key={j} whiteSpace="normal">{c}</Td>)}</Tr>)}</Tbody>
      </Table>
    </TableContainer>
  )
}

const statusColor = { pass: 'green', ok: 'green', warn: 'orange', fail: 'red', error: 'red', info: 'gray' }
const StatusBadge = ({ s }) => <Badge colorScheme={statusColor[s] ?? 'gray'}>{s}</Badge>

// --- markdown ----------------------------------------------------------------
// react-markdown never renders raw HTML and drops javascript: URLs, so agent-authored
// pages can't inject markup. Wikilinks become internal #/wl/ links resolved on click.

function Markdown({ text }) {
  const { index } = useVault()
  const link = useColorModeValue('purple.600', 'purple.300')
  const components = {
    a({ href = '', children }) {
      if (href === '#/prov/') {
        return <Badge variant="outline" colorScheme="gray" fontWeight="normal" textTransform="none" fontSize="0.7em" ms="1" verticalAlign="middle">{children}</Badge>
      }
      if (href.startsWith('#/wl/')) {
        const target = decodeURIComponent(href.slice(5))
        const node = index?.resolve(target)
        // An unaliased [[path/to/page]] reads better as the page's title.
        const bare = [].concat(children).join('') === target
        return node
          ? <Link href={pageHref(node.path)} color={link}>{bare && node.title ? node.title : children}</Link>
          : <Text as="span" color="muted" textDecoration="underline dotted" title="no such page">{children}</Text>
      }
      // react-markdown blanks unsafe URLs (javascript:, data:); show those as text.
      if (!href) return <Text as="span">{children}</Text>
      return <Link href={href} color={link} isExternal={/^https?:/.test(href)}>{children}</Link>
    },
  }
  return (
    <Box className="md" sx={{
      'h1,h2,h3,h4': { fontWeight: 'semibold', mt: 6, mb: 2, lineHeight: 'short' },
      h1: { fontSize: '2xl' }, h2: { fontSize: 'xl' }, h3: { fontSize: 'lg' },
      'p,ul,ol,pre,table,blockquote': { mb: 3 }, 'ul,ol': { pl: 6 }, li: { mb: 1 },
      code: { fontSize: '0.875em', px: 1, borderRadius: 'sm', bg: 'blackAlpha.100', _dark: { bg: 'whiteAlpha.200' } },
      pre: { p: 3, borderRadius: 'md', overflowX: 'auto', bg: 'blackAlpha.50', _dark: { bg: 'whiteAlpha.100' } },
      'pre code': { bg: 'transparent', px: 0 },
      blockquote: { borderLeftWidth: 3, pl: 4, color: 'muted' },
      table: { display: 'block', overflowX: 'auto' }, 'th,td': { borderWidth: 1, px: 2, py: 1, minW: '6rem' },
      lineHeight: 'tall',
    }}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>{withLinks(text)}</ReactMarkdown>
    </Box>
  )
}

// --- views -------------------------------------------------------------------
export function Overview() {
  const { status, graph, index, todos } = useVault()
  const log = useFetch('/v1/pages/log.md')
  if (!status) return <Loading />
  const hubs = index ? [...index.inbound.entries()].sort((a, b) => b[1].length - a[1].length).slice(0, 8) : []
  const stat = (label, n, help) => (
    <Card variant="outline"><CardBody><Stat><StatLabel color="muted">{label}</StatLabel><StatNumber>{n ?? '—'}</StatNumber>{help && <StatHelpText mb="0">{help}</StatHelpText>}</Stat></CardBody></Card>
  )
  return (
    <>
      <Header title="Overview" description={status.last_ingest ? `Last ingest ${status.last_ingest}` : status.pages ? undefined : 'Nothing ingested yet — run wiki-ingest.'} />
      <Body>
        <SimpleGrid columns={{ base: 2, md: 3, xl: 6 }} spacing="4" mb="6">
          {stat('Pages', status.pages)}
          {stat('Links', graph?.edges.length)}
          {stat('Categories', Object.keys(status.categories).length)}
          {stat('Open threads', todos.length)}
          {stat('_raw', status.raw_count, 'awaiting ingest')}
          {stat('Staged', status.staging_count, 'awaiting review')}
        </SimpleGrid>
        <SimpleGrid columns={{ base: 1, lg: 2 }} spacing="4">
          <Section title="Recently changed">
            <Stack spacing="1">{status.recent_pages.filter((p) => !index || index.byPath.has(p.path)).slice(0, 10).map((p) => (
              <Flex key={p.path} justify="space-between" gap="4" fontSize="sm">
                <Link href={pageHref(p.path)} noOfLines={1} title={p.path}>{nameOf(index, p.path)}</Link>
                <Text color="muted" flexShrink="0">{p.modified.slice(0, 10)}</Text>
              </Flex>
            ))}</Stack>
          </Section>
          <Section title="Recent activity">
            {log.data ? <Timeline entries={parseLog(log.data.markdown).slice(0, 8)} compact /> : <Text color="muted" fontSize="sm">{log.error ? 'No log.md yet.' : 'Loading…'}</Text>}
          </Section>
          <Section title="Hubs (most linked-to)">
            <Stack spacing="1">{hubs.map(([id, ins]) => (
              <Flex key={id} justify="space-between" fontSize="sm"><Link href={pageHref(index.byId.get(id).path)} noOfLines={1}>{nameOf(index, index.byId.get(id).path)}</Link><Text color="muted" flexShrink="0" ms="4">{ins.length} backlinks</Text></Flex>
            ))}</Stack>
          </Section>
          <Section title="Open threads">
            {todos.length ? <Stack spacing="2">{todos.slice(0, 6).map((t) => (
              <Text key={t.id} fontSize="sm"><Code mr="2">{t.id}</Code>{t.text}{t.stale && <Badge ms="2" colorScheme="orange">stale</Badge>}</Text>
            ))}</Stack> : <Text color="muted" fontSize="sm">No open threads.</Text>}
          </Section>
        </SimpleGrid>
      </Body>
    </>
  )
}

export function Pages({ params }) {
  const { graph, index } = useVault()
  const q = params.get('q') ?? ''
  const cat = params.get('cat') ?? ''
  const [filter, setFilter] = useState('')
  const hits = useFetch(q && `/v1/search?q=${encodeURIComponent(q)}&limit=30`, [q])
  if (!graph) return <Loading />

  if (q) {
    const rows = hits.data?.candidates ?? []
    return (
      <>
        <Header title={`Search: ${q}`} description={`${rows.length} ranked matches from the graph-aware retriever.`} />
        <Body>
          {hits.error ? <ErrorState message={hits.error} /> : !hits.data ? <Loading /> : !rows.length
            ? <EmptyState title="No matches" description="Try fewer or different words." />
            : <Stack spacing="3">{rows.map((c) => (
              <Card key={c.page} variant="outline" as="a" href={pageHref(c.page)} _hover={{ borderColor: 'purple.400' }}>
                <CardBody py="3">
                  <Flex gap="2" align="center"><Text fontWeight="medium">{c.title || titleOf(c.page)}</Text><Badge>{c.tier}</Badge><Text ms="auto" fontSize="xs" color="muted">{c.page}</Text></Flex>
                  {c.summary && <Text fontSize="sm" color="muted" mt="1" noOfLines={2}>{c.summary}</Text>}
                </CardBody>
              </Card>
            ))}</Stack>}
        </Body>
      </>
    )
  }

  const f = filter.toLowerCase()
  const rows = graph.nodes
    .filter((n) => (!cat || n.category === cat) && (!f || n.path.toLowerCase().includes(f) || n.tags.some((t) => t.includes(f))))
    .sort((a, b) => a.path.localeCompare(b.path))
  return (
    <>
      <Header title={cat || 'All pages'} description={`${rows.length} pages`}>
        <Input size="sm" maxW="64" placeholder="Filter by name or tag" value={filter} onChange={(e) => setFilter(e.target.value)} />
      </Header>
      <Body>
        <DataTable head={['Page', 'Category', 'Tags', 'In', 'Out']} rows={rows.map((n) => [
          <Link href={pageHref(n.path)} fontWeight="medium">{n.title || titleOf(n.path)}</Link>,
          <Text color="muted">{n.category}</Text>,
          <Wrap spacing="1">{n.tags.slice(0, 4).map((t) => <Tag key={t} size="sm">{t}</Tag>)}</Wrap>,
          index.inbound.get(n.id).length,
          index.outbound.get(n.id).length,
        ])} />
      </Body>
    </>
  )
}

function LinkList({ title, ids }) {
  const { index } = useVault()
  return (
    <Box>
      <Text fontSize="xs" fontWeight="semibold" textTransform="uppercase" color="muted" mb="2">{title} · {ids.length}</Text>
      {ids.length ? <Stack spacing="1">{[...new Set(ids)].map((id) => {
        const n = index.byId.get(id)
        return n && <Link key={id} href={pageHref(n.path)} fontSize="sm" noOfLines={1} title={n.path}>{n.title || titleOf(n.path)}</Link>
      })}</Stack> : <Text fontSize="sm" color="muted">None</Text>}
    </Box>
  )
}

// The frontmatter worth showing a reader; the rest (provenance, relationships,
// ledger fields) is machine bookkeeping and stays in the file.
const PROPS = [['summary', 'Summary'], ['category', 'Category'], ['tags', 'Tags'], ['aliases', 'Aliases'],
  ['lifecycle', 'Lifecycle'], ['tier', 'Tier'], ['base_confidence', 'Confidence'], ['created', 'Created'], ['updated', 'Updated']]

export function PageView({ path }) {
  const { index, status } = useVault()
  const page = useFetch(`/v1/pages/${path.split('/').map(encodeURIComponent).join('/')}`)
  const [props, body] = useMemo(() => (page.data ? splitFrontmatter(page.data.markdown) : [[], '']), [page.data])
  const node = index?.byPath.get(path)
  if (page.error) return <ErrorState message={page.error} />
  if (!page.data) return <Loading />
  const title = props.find(([k]) => k === 'title')?.[1] || titleOf(path)
  const byKey = Object.fromEntries(props)
  const shown = PROPS.filter(([k]) => byKey[k]).map(([k, label]) => [label, byKey[k]])
  const obsidian = status && `obsidian://open?path=${encodeURIComponent(`${status.vault}/${path}`)}`
  return (
    <Flex direction={{ base: 'column', xl: 'row' }} gap="6" px={{ base: 5, md: 8 }} pt="6" pb="10">
      <Box flex="1" minW="0" maxW="3xl">
        <Text fontSize="xs" color="muted">{path}</Text>
        <Heading size="lg" mt="1" mb="4">{title}</Heading>
        <Markdown text={body.replace(/^\s*# .*\n/, (h) => (h.trim().slice(2).trim().toLowerCase() === title.toLowerCase() ? '' : h))} />
      </Box>
      <Stack w={{ base: 'full', xl: '72' }} flexShrink="0" spacing="5" position={{ xl: 'sticky' }} top="6" alignSelf="start">
        {obsidian && <Button as="a" href={obsidian} size="sm" variant="outline" leftIcon={<ExternalLink size={14} />}>Open in Obsidian</Button>}
        {shown.length > 0 && (
          <Section title="Properties">
            <PropertyList>{shown.map(([k, v]) => <Property key={k} label={k} labelWidth="24" value={/^\[.*\]$/.test(v)
              ? <Wrap spacing="1">{v.slice(1, -1).split(',').map((t) => t.trim()).filter(Boolean).map((t) => <Tag key={t} size="sm">{t}</Tag>)}</Wrap>
              : <Text fontSize="sm" wordBreak="break-word" noOfLines={4} title={v}>{/^\d{4}-\d\d-\d\dT/.test(v) ? v.slice(0, 10) : v || '—'}</Text>} />)}</PropertyList>
          </Section>
        )}
        {node && <><LinkList title="Backlinks" ids={index.inbound.get(node.id)} /><Divider /><LinkList title="Links to" ids={index.outbound.get(node.id)} /></>}
      </Stack>
    </Flex>
  )
}

// Category colours always come with the category name in the legend, never alone.
const PALETTE = ['purple.400', 'teal.400', 'orange.400', 'blue.400', 'pink.400', 'green.400', 'yellow.500', 'cyan.400', 'red.400', 'gray.400']
const esc = (s) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)

export function GraphView() {
  const { graph, index } = useVault()
  const box = useRef(null)
  const fg2d = useRef(null)
  const [size, setSize] = useState({ w: 800, h: 600 })
  const [hl, setHl] = useState('')
  const colors = useToken('colors', PALETTE)
  const fg = useColorModeValue('#1a202c', '#e2e8f0')
  const edge = useColorModeValue('rgba(0,0,0,0.12)', 'rgba(255,255,255,0.12)')
  useEffect(() => {
    if (!box.current) return
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }))
    ro.observe(box.current)
    return () => ro.disconnect()
  }, [graph])
  // Refit when the frame changes size, once the first layout has settled.
  useEffect(() => { if (fg2d.fitted) fg2d.current?.zoomToFit(0, 40) }, [size])
  const cats = useMemo(() => {
    const counts = {}
    graph?.nodes.forEach((n) => { counts[n.category] = (counts[n.category] ?? 0) + 1 })
    return Object.entries(counts).sort((a, b) => b[1] - a[1])
  }, [graph])
  const data = useMemo(() => graph && ({
    nodes: graph.nodes.map((n) => ({ ...n })),
    links: graph.edges.map(([source, target]) => ({ source, target })),
  }), [graph])
  if (!graph) return <Loading />
  if (!graph.nodes.length) return <EmptyState title="No pages yet" description="Ingest something with wiki-ingest and the link graph shows up here." py="16" />
  const color = (c) => colors[Math.max(0, cats.findIndex(([k]) => k === c)) % colors.length]
  const q = hl.toLowerCase()
  const match = (n) => q && n.path.toLowerCase().includes(q)
  return (
    <Flex direction="column" h="100vh">
      <Header title="Graph" description={`${graph.nodes.length} pages · ${graph.edges.length} links. Click a node to open it; scroll to zoom.`}>
        <Input size="sm" maxW="56" placeholder="Highlight pages" value={hl} onChange={(e) => setHl(e.target.value)} />
      </Header>
      <Wrap px="8" pb="3" spacing="3">{cats.map(([c, n]) => (
        <HStack key={c} spacing="1.5" fontSize="xs"><Box w="2.5" h="2.5" borderRadius="full" bg={color(c)} /><Text>{c}</Text><Text color="muted">{n}</Text></HStack>
      ))}</Wrap>
      <Box ref={box} flex="1" minH="0" mx="8" mb="6" borderWidth="1px" borderRadius="lg" overflow="hidden">
        <ForceGraph2D
          ref={fg2d} onEngineStop={() => { if (!fg2d.fitted) { fg2d.fitted = true; fg2d.current?.zoomToFit(400, 40) } }}
          graphData={data} width={size.w} height={size.h} backgroundColor="rgba(0,0,0,0)"
          nodeLabel={(n) => esc(n.path)} linkColor={() => edge} cooldownTicks={120}
          onNodeClick={(n) => go(`/page/${encodeURIComponent(n.path)}`)}
          nodeCanvasObject={(n, ctx, scale) => {
            const deg = index.inbound.get(n.id).length
            const r = 2 + Math.sqrt(deg) * 1.6
            const on = match(n)
            ctx.globalAlpha = q && !on ? 0.2 : 1
            ctx.beginPath(); ctx.arc(n.x, n.y, on ? r + 2 : r, 0, 2 * Math.PI); ctx.fillStyle = color(n.category); ctx.fill()
            if (on || scale > 2.2 || deg >= 8) {
              ctx.font = `${11 / scale}px sans-serif`; ctx.fillStyle = fg; ctx.textAlign = 'center'
              ctx.fillText(n.title || titleOf(n.path), n.x, n.y + r + 10 / scale)
            }
            ctx.globalAlpha = 1
          }}
        />
      </Box>
    </Flex>
  )
}

const verbColor = { INGEST: 'purple', CAPTURE: 'teal', UPDATE: 'blue', LINT: 'orange', INIT: 'gray' }
function Timeline({ entries, compact }) {
  return (
    <Stack spacing={compact ? 2 : 3}>{entries.map((e, i) => {
      const page = e.fields.page
      const labelKey = ['title', 'page', 'source'].find((k) => e.fields[k])
      const label = labelKey ? e.fields[labelKey] : Object.entries(e.fields).map(([k, v]) => `${k}=${v}`).join(' ')
      const detail = labelKey ? Object.entries(e.fields).filter(([k]) => k !== labelKey && k !== 'page').map(([k, v]) => `${k}=${v}`).join('  ') : ''
      const when = compact || e.ts.endsWith('T00:00:00Z') ? e.ts.slice(0, 10) : e.ts.slice(0, 16).replace('T', ' ')
      return (
        <Flex key={i} gap="3" align="baseline" fontSize="sm" wrap={compact ? 'nowrap' : { base: 'wrap', md: 'nowrap' }}>
          <Text color="muted" flexShrink="0" w={compact ? '20' : '36'} fontFamily="mono" fontSize="xs">{when}</Text>
          <Badge colorScheme={verbColor[e.verb] ?? 'gray'} flexShrink="0">{e.verb}</Badge>
          <Box minW="0" flexBasis={compact ? undefined : { base: 'full', md: 'auto' }}>
            {page ? <Link href={pageHref(page)} noOfLines={compact ? 1 : 2}>{label}</Link> : <Text noOfLines={compact ? 1 : 3}>{label}</Text>}
            {!compact && detail && <Text color="muted" fontSize="xs" noOfLines={2}>{detail}</Text>}
          </Box>
        </Flex>
      )
    })}</Stack>
  )
}

export function ActivityView() {
  const log = useFetch('/v1/pages/log.md')
  const [verb, setVerb] = useState('')
  const entries = useMemo(() => (log.data ? parseLog(log.data.markdown) : []), [log.data])
  const verbs = [...new Set(entries.map((e) => e.verb))]
  if (log.error) return <EmptyState title="No activity yet" description="log.md fills as skills ingest, capture and lint." py="16" />
  if (!log.data) return <Loading />
  return (
    <>
      <Header title="Activity" description="Every ingest, capture and maintenance run, from log.md." />
      <Body>
        <Wrap mb="5">
          <Button size="xs" variant={verb ? 'ghost' : 'solid'} onClick={() => setVerb('')}>All {entries.length}</Button>
          {verbs.map((v) => <Button key={v} size="xs" variant={verb === v ? 'solid' : 'ghost'} onClick={() => setVerb(v)}>{v} {entries.filter((e) => e.verb === v).length}</Button>)}
        </Wrap>
        <Timeline entries={entries.filter((e) => !verb || e.verb === verb)} />
      </Body>
    </>
  )
}

export function MemoryView() {
  const { setTodos } = useVault()
  const [tick, setTick] = useState(0)
  const facts = useFetch('/v1/memory/profile', [tick])
  const todos = useFetch('/v1/memory/todos?include_closed=true', [tick])
  const [text, setText] = useState('')
  const act = async (path, body) => {
    await api.post(path, body)
    setTick((t) => t + 1)
    api.get('/v1/memory/todos').then((t) => setTodos(t.todos))
  }
  return (
    <>
      <Header title="Profile & threads" description="Durable facts about you and open threads carried between sessions (_meta/profile.md, _meta/todos.md)." />
      <Body>
        <Stack spacing="4">
          <Section title="Profile">
            {facts.error ? <Text color="red.400">{facts.error}</Text> : !facts.data ? <Skeleton h="10" /> : (
              <DataTable empty="No facts yet — agents add them with `obsidian-wiki memory profile set`." head={['Key', 'Value', 'Confidence', 'Source', 'Until', '']}
                rows={facts.data.facts.map((f) => [<Code>{f.key}</Code>, f.value, f.confidence, f.source, f.until || '—',
                  <Button size="xs" variant="ghost" colorScheme="red" onClick={() => act('/v1/memory/profile', { action: 'forget', key: f.key })}>Forget</Button>])} />
            )}
          </Section>
          <Section title="Threads">
            <form onSubmit={(e) => { e.preventDefault(); if (text.trim()) act('/v1/memory/todos', { action: 'add', text, origin: 'ui' }).then(() => setText('')) }}>
              <HStack mb="4"><Input size="sm" placeholder="Add a thread to carry into the next session" value={text} onChange={(e) => setText(e.target.value)} /><Button size="sm" type="submit" colorScheme="purple">Add</Button></HStack>
            </form>
            {todos.data && (
              <DataTable empty="No threads." head={['ID', 'Thread', 'Status', 'Touched', '']}
                rows={todos.data.todos.map((t) => [<Code>{t.id}</Code>, <Text>{t.text}{t.origin && <Text as="span" color="muted" fontSize="xs"> — {t.origin}</Text>}</Text>,
                  <HStack><Badge colorScheme={t.status === 'open' ? 'purple' : 'gray'}>{t.status}</Badge>{t.stale && <Badge colorScheme="orange">stale</Badge>}</HStack>,
                  <Text whiteSpace="nowrap">{t.touched?.slice(0, 10)}</Text>,
                  t.status === 'open' && <HStack spacing="1"><Button size="xs" variant="ghost" onClick={() => act('/v1/memory/todos', { action: 'done', todo_id: t.id })}>Done</Button><Button size="xs" variant="ghost" onClick={() => act('/v1/memory/todos', { action: 'drop', todo_id: t.id })}>Drop</Button></HStack>])} />
            )}
          </Section>
        </Stack>
      </Body>
    </>
  )
}

export function HotView() {
  const hot = useFetch('/v1/pages/hot.md')
  if (hot.error) return <EmptyState title="No hot cache yet" description="hot.md is written by `obsidian-wiki memory sync` after each write skill." py="16" />
  if (!hot.data) return <Loading />
  return <><Header title="Hot cache" description="hot.md — the ~500-word snapshot the next session starts from." /><Body maxW="4xl"><Markdown text={splitFrontmatter(hot.data.markdown)[1]} /></Body></>
}

export function HealthView() {
  const h = useFetch('/v1/health')
  return (
    <>
      <Header title="Health" description="wiki doctor and wiki-lint, run live against the vault." />
      <Body>
        {h.error ? <ErrorState message={h.error} /> : !h.data ? <Loading /> : (
          <SimpleGrid columns={{ base: 1, xl: 2 }} spacing="4">
            <Section title={<HStack><span>Doctor</span><StatusBadge s={h.data.doctor.status} /></HStack>}>
              <DataTable empty="Every check passes." head={['Check', 'Status', 'Detail']}
                rows={h.data.doctor.checks.filter((c) => c.status !== 'pass').map((c) => [c.name, <StatusBadge s={c.status} />, <Stack spacing="0.5">{String(c.detail).split('; ').map((d, i) => <Text key={i}>{d}</Text>)}</Stack>])} />
            </Section>
            <Section title={<HStack><span>Lint</span><StatusBadge s={h.data.lint.status} /></HStack>}>
              <Text fontSize="sm" color="muted" mb="3">{h.data.lint.stats.pages} pages, {h.data.lint.stats.link_count} links. Fix with /wiki-lint.</Text>
              <DataTable empty="No findings." head={['Finding', 'Count']}
                rows={Object.entries(h.data.lint.stats.findings).filter(([, n]) => n).map(([k, n]) => [k.replace(/_/g, ' '), n])} />
            </Section>
          </SimpleGrid>
        )}
      </Body>
    </>
  )
}

export function StagingView() {
  const st = useFetch('/v1/staging')
  return (
    <>
      <Header title="Staging" description="Agent writes waiting for review. Promote or discard with /wiki-stage-commit." />
      <Body>
        {st.error ? <ErrorState message={st.error} /> : !st.data ? <Loading /> : !st.data.count
          ? <EmptyState title="Nothing staged" description="Skills that stage writes (wiki-playbook-review, staged ingests) park them in _staging/ for you to approve." py="12" />
          : <Stack spacing="3">{st.data.items.map((it) => (
            <Section key={it.staged_path} title={<HStack><Badge>{it.kind}</Badge><span>{it.live_path}</span></HStack>}>
              <Box as="pre" fontSize="xs" overflowX="auto" maxH="96">{(it.diff || '(identical)').split('\n').map((l, i) => (
                <Box key={i} color={l.startsWith('+') ? 'green.500' : l.startsWith('-') ? 'red.400' : undefined}>{l || ' '}</Box>
              ))}</Box>
            </Section>
          ))}</Stack>}
      </Body>
    </>
  )
}

export function SourcesView() {
  const { status } = useVault()
  if (!status) return <Loading />
  const g = status.git
  return (
    <>
      <Header title="Sources & git" description="What .manifest.json says was ingested, and the vault's git state." />
      <Body>
        <Stack spacing="4">
          <Section title="Sources">
            <DataTable empty="No sources in .manifest.json." head={['Source', 'Type', 'Ingested', 'Pages', 'Missing']}
              rows={status.sources.map((s) => [<Text noOfLines={2} maxW="md">{s.source_id}</Text>, s.type, s.ingested_at?.slice(0, 10), s.pages_produced,
                s.missing_pages.length ? <Badge colorScheme="red">{s.missing_pages.length}</Badge> : '—'])} />
          </Section>
          <Section title="Git">
            {!g.repo ? <Text color="muted" fontSize="sm">The vault is not a git repository.</Text> : (
              <>
                <Text fontSize="sm" mb="2">Branch <Code>{g.branch}</Code> · {g.dirty_count} uncommitted</Text>
                <Box as="pre" fontSize="xs" overflowX="auto">{[...g.dirty, '', ...g.recent].join('\n')}</Box>
              </>
            )}
          </Section>
        </Stack>
      </Body>
    </>
  )
}

function CodeBlock({ code, label, lang, wrap }) {
  const { hasCopied, onCopy } = useClipboard(code)
  return (
    <Box borderWidth="1px" borderRadius="md" overflow="hidden">
      <Flex align="center" px="3" py="1" borderBottomWidth="1px" bg="blackAlpha.50" _dark={{ bg: 'whiteAlpha.50' }}>
        <Text fontSize="xs" color="muted" fontFamily="mono">{lang}</Text>
        <Button size="xs" ms="auto" variant="ghost" onClick={onCopy}
          leftIcon={hasCopied ? <Check size={12} /> : <Copy size={12} />} aria-label={`Copy ${label ?? 'snippet'}`}>
          {hasCopied ? 'Copied' : 'Copy'}
        </Button>
      </Flex>
      {/* Phones wrap long paths instead of scrolling; Copy still copies the exact text. */}
      <Box as="pre" fontSize="xs" p="3" overflowX="auto" whiteSpace={{ base: 'pre-wrap', md: wrap ? 'pre-wrap' : 'pre' }}
        wordBreak={{ base: 'break-all', md: 'normal' }}>{code}</Box>
    </Box>
  )
}

const MORE = [
  ['Install the wiki skills into every agent', 'Adds /wiki-query, /wiki-capture, /wiki-ingest and the rest to Claude Code, Codex, Cursor, Gemini, Windsurf and 10+ more, plus the bootstrap files that point them at this vault.', 'obsidian-wiki setup'],
  ['Automatic recall in Claude Code', 'Injects your recap at session start and asks for a capture at session end, with no tool calls needed.', 'obsidian-wiki hooks install'],
  ['Agents without MCP', 'Paste the recap into any chat, or let a shell-capable agent call the CLI.', 'obsidian-wiki memory recap --max-words 350\nobsidian-wiki query "what did I decide about X"'],
  ['From your own code', 'In-process, no server or key.', 'from obsidian_wiki import Memory\nmemory = Memory("~/brain")\nmemory.recap()\nmemory.search("postgres")'],
]

export function ConnectView() {
  const info = useFetch('/v1/connect')
  const [transport, setTransport] = useState('stdio')
  if (info.error) return <ErrorState message={info.error} />
  if (!info.data) return <Loading />
  const { python, vault, key_required: keyRequired, tools, oauth, public_url: publicUrl } = info.data
  // Behind a proxy the browser's origin may differ from the address agents use.
  const url = `${publicUrl || window.location.origin}/mcp/`
  const snippets = connectSnippets({ python, vault, url, keyRequired, oauth }, transport)
  const step = (n, title) => <HStack><Badge colorScheme="purple" borderRadius="full" px="2">{n}</Badge><span>{title}</span></HStack>
  return (
    <>
      <Header title="Connect an agent" description="Give any MCP-capable agent this vault as long-term memory: search, read, write, recap, profile and threads." />
      <Body>
        <Stack spacing="4" maxW="5xl">
          <Section title={step(1, 'Add the memory server to your agent')}>
            <HStack mb="3" spacing="2">
              <Button size="sm" variant={transport === 'stdio' ? 'solid' : 'outline'} colorScheme="purple" onClick={() => setTransport('stdio')}>This machine (stdio)</Button>
              <Button size="sm" variant={transport === 'http' ? 'solid' : 'outline'} colorScheme="purple" onClick={() => setTransport('http')}>Over HTTP</Button>
            </HStack>
            <Text fontSize="sm" color="muted" mb="4">
              {transport === 'stdio'
                ? <>The agent launches its own memory process, so it needs no server running. These configs use this machine's Python (<Code fontSize="xs" wordBreak="break-all">{python}</Code>) and vault (<Code fontSize="xs" wordBreak="break-all">{vault}</Code>), so they work in GUI apps that can't see your PATH.</>
                : <>The agent talks to this server at <Code fontSize="xs">{url}</Code>, so it only works while the server is running. {keyRequired
                  ? <>Set <Code fontSize="xs">WIKI_API_KEY</Code> in the agent's environment. The key is never written into these configs.</>
                  : <>This server runs without a key (loopback only). Start it with <Code fontSize="xs">WIKI_API_KEY</Code> set before exposing it.</>}
                  {oauth && <> OAuth sign-in is on: clients that support it (claude.ai, Cursor, VS Code, <Code fontSize="xs">codex mcp login</Code>) can drop the header and sign in with your vault key instead.</>}</>}
            </Text>
            <Tabs variant="soft-rounded" colorScheme="purple" size="sm" isLazy>
              <TabList flexWrap="wrap" gap="1">{snippets.map((s) => <Tab key={s.id}>{s.label}</Tab>)}</TabList>
              <TabPanels>{snippets.map((s) => (
                <TabPanel key={s.id} px="0">
                  <Text fontSize="sm" mb="2"><Text as="span" color="muted">Where: </Text>{s.where}</Text>
                  <CodeBlock code={s.code} label={`${s.label} config`} lang={s.lang} />
                  {s.note && <Text fontSize="xs" color="muted" mt="2">{s.note}</Text>}
                  {s.lang === 'json' && <Text fontSize="xs" color="muted" mt="2">If the file already exists, merge this server into its existing block rather than replacing the file.</Text>}
                </TabPanel>
              ))}</TabPanels>
            </Tabs>
          </Section>

          <Section title={step(2, 'Tell it to use the memory')}>
            <Text fontSize="sm" color="muted" mb="3">Having the tools isn't the same as using them. Paste this into the agent's instructions (<Code fontSize="xs">AGENTS.md</Code>, <Code fontSize="xs">CLAUDE.md</Code>, <Code fontSize="xs">GEMINI.md</Code>, Cursor rules, or a system prompt).</Text>
            <CodeBlock code={AGENT_INSTRUCTIONS} label="agent instructions" lang="markdown" wrap />
          </Section>

          <Section title={step(3, 'Check it works')}>
            <Text fontSize="sm">Restart the agent and ask: <Text as="em">"What's in my memory recap?"</Text> It should call <Code fontSize="xs">memory_recap</Code> and answer with your open threads.</Text>
            <Text fontSize="sm" color="muted" mt="2">The {tools.length} tools it gets:</Text>
            <Box mt="2"><DataTable head={['Tool', 'What it does']} rows={tools.map((t) => [<Code fontSize="xs">{t.name}</Code>, t.description])} /></Box>
          </Section>

          <Section title="More ways in">
            <SimpleGrid columns={{ base: 1, lg: 2 }} spacing="5">{MORE.map(([title, desc, code]) => (
              <Box key={title}>
                <Text fontWeight="medium" fontSize="sm">{title}</Text>
                <Text fontSize="sm" color="muted" mb="2">{desc}</Text>
                <CodeBlock code={code} label={title} lang={code.startsWith('from ') ? 'python' : 'bash'} wrap />
              </Box>
            ))}</SimpleGrid>
          </Section>
        </Stack>
      </Body>
    </>
  )
}
