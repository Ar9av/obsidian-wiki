import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import {
  Badge, Box, Button, Flex, IconButton, Menu, MenuButton, MenuDivider, MenuItemOption, MenuList, MenuOptionGroup, Spacer, Text, Tooltip,
  extendTheme, useColorMode, useToast,
} from '@chakra-ui/react'
import {
  AppShell, NavGroup, NavItem, SaasProvider, SearchInput, Sidebar, SidebarSection, SidebarToggleButton, theme as saasTheme, useSidebarContext,
} from '@saas-ui/react'
import {
  Activity, BookOpen, Brain, ChevronsUpDown, ClipboardCheck, FileText, Flame, GitBranch, HeartPulse, Inbox, LayoutDashboard, Lightbulb, Moon,
  Network, Play, Plug, RefreshCw, Settings, Sparkles, Sun,
} from 'lucide-react'
import * as V from './views.jsx'
import * as T from './tools.jsx'
import { slug } from './lib.js'

// --- API -------------------------------------------------------------------
// The key is asked for only if the server rejects us, then kept in sessionStorage
// and sent as a bearer header — the same auth every other API client uses.
const KEY = 'obsidian-wiki-key'
// Views fire several requests at once; only the first 401 prompts. The rest see
// the key changed while they were in flight and retry, or stop if it was declined.
let declined = false
async function call(path, init = {}) {
  const sent = sessionStorage.getItem(KEY) ?? ''
  const headers = { authorization: `Bearer ${sent}`, ...(init.body ? { 'content-type': 'application/json' } : {}) }
  const res = await fetch(path, { ...init, headers })
  if (res.status === 401) {
    if ((sessionStorage.getItem(KEY) ?? '') !== sent) return call(path, init)
    const key = declined ? null : window.prompt('WIKI_API_KEY for this server')
    if (key) { sessionStorage.setItem(KEY, key); return call(path, init) }
    declined = true
    throw new Error('bad or missing API key — refresh to try again')
  }
  if (!res.ok) throw new Error(`${path}: ${res.status} ${await res.text()}`)
  return res.json()
}
export const api = {
  get: (path) => call(path),
  post: (path, body) => call(path, { method: 'POST', body: JSON.stringify(body) }),
}

// --- shared vault state ----------------------------------------------------
const Vault = createContext(null)
export const useVault = () => useContext(Vault)

function useVaultData() {
  const [status, setStatus] = useState(null)
  const [graph, setGraph] = useState(null)
  const [todos, setTodos] = useState([])
  const [vaults, setVaults] = useState(null)
  const [error, setError] = useState(null)
  const load = useCallback(() => {
    declined = false
    setError(null)
    api.get('/v1/status').then(setStatus).catch((e) => setError(e.message))
    api.get('/v1/graph').then(setGraph).catch((e) => setError(e.message))
    api.get('/v1/memory/todos').then((t) => setTodos(t.todos)).catch(() => {})
    api.get('/v1/vaults').then(setVaults).catch(() => {})
  }, [])
  // The server holds one current vault; switching repoints it, then every view reloads.
  const switchVault = useCallback(async (path) => {
    await api.post('/v1/vaults', { path })
    setStatus(null); setGraph(null)
    go('/')
    load()
  }, [load])
  useEffect(load, [load])

  const index = useMemo(() => {
    if (!graph) return null
    const byId = new Map(graph.nodes.map((n) => [n.id, n]))
    const byKey = new Map(graph.nodes.map((n) => [slug(n.path), n]))
    const inbound = new Map(graph.nodes.map((n) => [n.id, []]))
    const outbound = new Map(graph.nodes.map((n) => [n.id, []]))
    for (const [s, t] of graph.edges) { outbound.get(s)?.push(t); inbound.get(t)?.push(s) }
    // Wikilinks resolve the way PageIndex does for the common cases: page id
    // (unique stem), slugged path, or a path suffix.
    const resolve = (target) => {
      const k = slug(target.split('#')[0])
      if (byId.has(k)) return byId.get(k)
      if (byKey.has(k)) return byKey.get(k)
      return graph.nodes.find((n) => slug(n.path).endsWith('/' + k)) ?? null
    }
    const byPath = new Map(graph.nodes.map((n) => [n.path, n]))
    return { byId, byPath, inbound, outbound, resolve }
  }, [graph])

  return { status, graph, index, todos, setTodos, vaults, switchVault, error, reload: load }
}

// --- routing ---------------------------------------------------------------
// Hash routes so every view deep-links: #/page/concepts/x.md, #/pages?cat=concepts.
function useRoute() {
  const parse = () => {
    const [path, qs] = window.location.hash.replace(/^#/, '').split('?')
    return { path: path || '/', params: new URLSearchParams(qs) }
  }
  const [route, setRoute] = useState(parse)
  useEffect(() => {
    const on = () => { setRoute(parse()); document.querySelector('main')?.scrollTo?.(0, 0) }
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return route
}
export const go = (hash) => { window.location.hash = hash }

// --- shell -----------------------------------------------------------------
function Count({ n }) {
  return n == null ? null : <Badge ms="auto" variant="subtle" colorScheme="gray" fontWeight="normal">{n}</Badge>
}

// Below the breakpoint the sidebar is a drawer; close it once a view is picked.
// (Passing isOpen to Sidebar would make it collapsible at every width.)
function CloseOnNavigate({ route }) {
  const { isMobile, onClose } = useSidebarContext()
  useEffect(() => { if (isMobile) onClose() }, [route])
  return null
}

function VaultSwitcher({ compact }) {
  const { status, vaults, switchVault } = useVault()
  const toast = useToast()
  const current = vaults?.current ?? status?.vault
  const name = current?.split('/').pop() ?? '…'
  const pick = (path) => path !== current && switchVault(path).catch((e) => toast({ status: 'error', title: 'Could not switch', description: e.message }))
  return (
    <Menu placement="bottom-start">
      <Tooltip label={current} openDelay={500}>
        <MenuButton as={Button} size="sm" variant="ghost" px="2" h={compact ? '8' : '11'} textAlign="left" minW="0" maxW="full" flex="1">
          <Flex align="center" gap="2" minW="0">
            <Box lineHeight="short" minW="0" flex="1">
              {!compact && <Text fontWeight="semibold" fontSize="sm">Obsidian Wiki</Text>}
              <Text fontSize={compact ? 'sm' : 'xs'} fontWeight={compact ? 'semibold' : 'normal'} color={compact ? undefined : 'muted'} noOfLines={1}>{name}</Text>
            </Box>
            <ChevronsUpDown size={14} style={{ flexShrink: 0 }} />
          </Flex>
        </MenuButton>
      </Tooltip>
      <MenuList zIndex="popover" maxW="sm">
        <MenuOptionGroup title="Switch vault" type="radio" value={current} onChange={pick}>
          {(vaults?.vaults ?? []).map((v) => (
            <MenuItemOption key={v.path} value={v.path} isDisabled={!v.exists}>
              <Text fontSize="sm">{v.label} <Text as="span" color="muted" fontSize="xs">{v.name === 'startup' ? '' : `@${v.name}`}{v.exists ? '' : ' (missing)'}</Text></Text>
              <Text fontSize="xs" color="muted" noOfLines={1}>{v.path}</Text>
            </MenuItemOption>
          ))}
        </MenuOptionGroup>
        <MenuDivider />
        <Text px="3" py="1" fontSize="xs" color="muted">Add vaults with /wiki-switch. Switching here changes this server only, not your default.</Text>
      </MenuList>
    </Menu>
  )
}

function AppSidebar({ route }) {
  const { status, todos, graph, reload } = useVault()
  const { colorMode, toggleColorMode } = useColorMode()
  const [q, setQ] = useState(route.params.get('q') ?? '')
  const at = (p) => route.path === p
  const item = (href, label, icon, n, active = at(href)) => (
    <NavItem href={`#${href}`} icon={icon} isActive={active}>
      <Flex w="full" align="center">{label}<Count n={n} /></Flex>
    </NavItem>
  )
  const cats = Object.entries(status?.categories ?? {}).filter(([c]) => c !== '(root)')
  const cat = route.params.get('cat')
  return (
    <Sidebar variant="inset" toggleBreakpoint="md" width="260px">
      <SidebarToggleButton />
      <CloseOnNavigate route={route} />
      <SidebarSection direction="row" pt={{ base: 12, md: 4 }} px="4">
        <Flex align="center" gap="1" minW="0" flex="1">
          <Box as={BookOpen} boxSize="5" color="purple.500" flexShrink="0" />
          <VaultSwitcher />
        </Flex>
        <Tooltip label="Reload vault data"><IconButton size="xs" variant="ghost" aria-label="Refresh" icon={<RefreshCw size={14} />} onClick={reload} /></Tooltip>
        <Tooltip label="Toggle theme"><IconButton size="xs" variant="ghost" aria-label="Toggle theme" icon={colorMode === 'dark' ? <Sun size={14} /> : <Moon size={14} />} onClick={toggleColorMode} /></Tooltip>
      </SidebarSection>
      <SidebarSection px="3">
        <form onSubmit={(e) => { e.preventDefault(); go(q ? `/pages?q=${encodeURIComponent(q)}` : '/pages') }}>
          <SearchInput size="sm" placeholder="Search the vault" value={q} onChange={(e) => setQ(e.target.value)} onReset={() => setQ('')} />
        </form>
      </SidebarSection>
      <SidebarSection flex="1" overflowY="auto" px="2">
        <NavGroup>
          {item('/', 'Overview', <LayoutDashboard />)}
          {item('/ask', 'Ask', <Sparkles />)}
          {item('/inbox', 'Inbox', <Inbox />, (status?.raw_files ?? status?.raw_count) || null)}
          {item('/actions', 'Actions', <Play />)}
          {item('/pages', 'Pages', <FileText />, status?.pages, at('/pages') && !cat)}
          {item('/graph', 'Graph', <Network />, graph?.edges.length)}
          {item('/insights', 'Insights', <Lightbulb />)}
          {item('/activity', 'Activity', <Activity />)}
          {item('/connect', 'Connect an agent', <Plug />)}
        </NavGroup>
        <NavGroup title="Memory" isCollapsible>
          {item('/memory', 'Profile & threads', <Brain />, todos.length)}
          {item('/hot', 'Hot cache', <Flame />)}
        </NavGroup>
        <NavGroup title="Maintenance" isCollapsible>
          {item('/health', 'Health', <HeartPulse />)}
          {item('/staging', 'Staging', <ClipboardCheck />, status?.staging_count)}
          {item('/sources', 'Sources & git', <GitBranch />, status?.sources.length)}
          {item('/settings', 'Settings', <Settings />)}
        </NavGroup>
        {cats.length > 0 && (
          <NavGroup title="Categories" isCollapsible defaultIsOpen>
            {cats.map(([c, n]) => (
              <NavItem key={c} href={`#/pages?cat=${encodeURIComponent(c)}`} isActive={cat === c}>
                <Flex w="full" align="center"><Text noOfLines={1}>{c}</Text><Count n={n} /></Flex>
              </NavItem>
            ))}
          </NavGroup>
        )}
      </SidebarSection>
    </Sidebar>
  )
}

function Router({ route }) {
  const p = route.path
  if (p.startsWith('/page/')) return <V.PageView path={decodeURIComponent(p.slice(6))} />
  const views = {
    '/': V.Overview, '/pages': V.Pages, '/graph': V.GraphView, '/activity': V.ActivityView, '/connect': V.ConnectView,
    '/memory': V.MemoryView, '/hot': V.HotView, '/health': V.HealthView, '/staging': V.StagingView, '/sources': V.SourcesView,
    '/ask': T.AskView, '/inbox': T.InboxView, '/actions': T.ActionsView, '/insights': T.InsightsView, '/settings': T.SettingsView,
  }
  const View = views[p] ?? V.NotFound
  return <View params={route.params} />
}

// Files dropped anywhere in the window go to the inbox; the Inbox view's own drop
// zone stops the event first, so nothing is uploaded twice.
function DropAnywhere({ children }) {
  const { reload } = useVault()
  const toast = useToast()
  const [over, setOver] = useState(false)
  const files = (e) => [...(e.dataTransfer?.types ?? [])].includes('Files')
  return (
    <Box as="main" h="100vh" overflowY="auto" position="relative"
      onDragOver={(e) => { if (files(e)) { e.preventDefault(); setOver(true) } }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setOver(false) }}
      onDrop={async (e) => {
        if (!files(e)) return
        e.preventDefault(); setOver(false)
        try {
          const saved = await T.uploadFiles([...e.dataTransfer.files])
          toast({ status: 'success', title: `Added ${saved.length} to the inbox`, description: 'They go in on the next ingest.' })
          reload()
        } catch (err) { toast({ status: 'error', title: 'Upload failed', description: err.message }) }
      }}>
      {children}
      {over && (
        <Flex position="fixed" inset="0" zIndex="overlay" align="center" justify="center" bg="blackAlpha.500" pointerEvents="none">
          <Box bg="chakra-body-bg" borderRadius="lg" px="8" py="6" borderWidth="2px" borderStyle="dashed" borderColor="purple.400">
            <Text fontWeight="semibold">Drop to add to the inbox</Text>
          </Box>
        </Flex>
      )}
    </Box>
  )
}

function App() {
  const vault = useVaultData()
  const route = useRoute()
  return (
    <Vault.Provider value={vault}>
      <AppShell variant="static" height="100vh" sidebar={<AppSidebar route={route} />}>
        <DropAnywhere>
          {/* Phones: a solid bar behind Saas UI's fixed drawer toggle (12px, 32px tall), so
              nothing floats over scrolling content. Desktop keeps its controls in the sidebar. */}
          <Flex display={{ base: 'flex', md: 'none' }} position="sticky" top="0" zIndex="sticky" h="14" align="center"
            pl="14" pr="2" bg="chakra-body-bg" borderBottomWidth="1px">
            <VaultSwitcher compact />
            <Spacer />
            <IconButton aria-label="Refresh" icon={<RefreshCw size={14} />} size="sm" variant="ghost" onClick={vault.reload} />
          </Flex>
          {vault.error ? <V.ErrorState message={vault.error} /> : <Router route={route} />}
        </DropAnywhere>
      </AppShell>
    </Vault.Provider>
  )
}

const theme = extendTheme({ config: { initialColorMode: 'system', useSystemColorMode: false } }, saasTheme)
createRoot(document.getElementById('root')).render(
  <SaasProvider theme={theme}><App /></SaasProvider>,
)
