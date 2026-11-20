import React, { useEffect, useRef, useState } from 'react'
import {
  Alert, AlertDescription, AlertIcon, Badge, Box, Button, Code, Flex, FormControl, FormHelperText, FormLabel, HStack, Input,
  InputGroup, InputRightElement, Link, Select, SimpleGrid, Spinner, Stack, Stat, StatLabel, StatNumber, Switch, Tab, TabList,
  TabPanel, TabPanels, Tabs, Text, Textarea, Wrap, WrapItem, useColorModeValue, useToast,
} from '@chakra-ui/react'
import { EmptyState } from '@saas-ui/react'
import { ArrowRight, Globe, Play, Send, Sparkles, Trash2, Upload } from 'lucide-react'
import { api, go, useVault } from './main.jsx'
import { Body, CodeBlock, DataTable, ErrorState, Header, Loading, Markdown, Section, nameOf, pageHref, useFetch } from './views.jsx'
import { nextActions } from './lib.js'

// --- inbox: anything dropped here lands in _raw/ for the next ingest -----------

const readB64 = (file) => new Promise((resolve, reject) => {
  const r = new FileReader()
  r.onload = () => resolve(String(r.result).split(',', 2)[1] ?? '')
  r.onerror = () => reject(r.error)
  r.readAsDataURL(file)
})

export async function uploadFiles(files) {
  const saved = []
  for (const file of files) {
    saved.push(await api.post('/v1/inbox', { kind: 'file', filename: file.name, data_b64: await readB64(file) }))
  }
  return saved
}

function DropZone({ onSaved }) {
  const input = useRef(null)
  const [over, setOver] = useState(false)
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  const accent = useColorModeValue('purple.500', 'purple.300')
  const send = async (files) => {
    if (!files.length) return
    setBusy(true)
    try {
      const saved = await uploadFiles(files)
      toast({ status: 'success', title: `Added ${saved.length} to _raw/`, description: 'They go in on the next ingest.' })
      onSaved?.()
    } catch (e) { toast({ status: 'error', title: 'Upload failed', description: e.message }) } finally { setBusy(false) }
  }
  return (
    <Box borderWidth="2px" borderStyle="dashed" borderRadius="lg" borderColor={over ? accent : 'inherit'} p="6" textAlign="center"
      cursor="pointer" onClick={() => input.current?.click()}
      onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setOver(true) }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); e.stopPropagation(); setOver(false); send([...e.dataTransfer.files]) }}>
      <input ref={input} type="file" multiple hidden onChange={(e) => { send([...e.target.files]); e.target.value = '' }} />
      {busy ? <Spinner /> : <Box as={Upload} mx="auto" boxSize="6" color="muted" />}
      <Text mt="2" fontWeight="medium">Drop files here, or click to choose</Text>
      <Text fontSize="sm" color="muted">PDFs, markdown, transcripts, exports, images. Up to 25 MB each.</Text>
    </Box>
  )
}

export function InboxView() {
  const [tick, setTick] = useState(0)
  const { reload } = useVault()
  const inbox = useFetch('/v1/inbox', [tick])
  const toast = useToast()
  const [note, setNote] = useState({ title: '', text: '' })
  const [link, setLink] = useState({ url: '', text: '' })
  const refresh = () => { setTick((t) => t + 1); reload() }
  const save = async (body, reset) => {
    try {
      await api.post('/v1/inbox', body)
      reset()
      toast({ status: 'success', title: 'Saved to _raw/' })
      refresh()
    } catch (e) { toast({ status: 'error', title: 'Not saved', description: e.message }) }
  }
  // A screenshot pasted into the note box becomes a file of its own.
  const onPaste = async (e) => {
    const files = [...e.clipboardData.files]
    if (!files.length) return
    e.preventDefault()
    await uploadFiles(files.map((f, i) => new File([f], f.name === 'image.png' ? `pasted-${Date.now()}-${i}.png` : f.name, { type: f.type })))
    toast({ status: 'success', title: `Pasted ${files.length} file${files.length > 1 ? 's' : ''} into _raw/` })
    refresh()
  }
  const items = inbox.data?.items ?? []
  return (
    <>
      <Header title="Inbox" description="Everything here waits in _raw/. The next wiki-ingest reads it, writes linked pages, and archives the originals.">
        <IngestButton disabled={!items.length} onDone={refresh} />
      </Header>
      <Body>
        <Stack spacing="4" maxW="5xl">
          <DropZone onSaved={refresh} />
          <Section>
            <Tabs variant="soft-rounded" colorScheme="purple" size="sm">
              <TabList><Tab>Paste a note</Tab><Tab>Add a link</Tab></TabList>
              <TabPanels>
                <TabPanel px="0">
                  <form onSubmit={(e) => { e.preventDefault(); save({ kind: 'text', ...note }, () => setNote({ title: '', text: '' })) }}>
                    <Stack>
                      <Input size="sm" placeholder="Title (optional)" value={note.title} onChange={(e) => setNote({ ...note, title: e.target.value })} />
                      <Textarea rows={8} placeholder="Paste text, meeting notes, a chat export… (paste a screenshot to attach it)"
                        value={note.text} onChange={(e) => setNote({ ...note, text: e.target.value })} onPaste={onPaste} />
                      <Button type="submit" size="sm" colorScheme="purple" alignSelf="start" isDisabled={!note.text.trim()}>Save to inbox</Button>
                    </Stack>
                  </form>
                </TabPanel>
                <TabPanel px="0">
                  <form onSubmit={(e) => { e.preventDefault(); save({ kind: 'url', ...link }, () => setLink({ url: '', text: '' })) }}>
                    <Stack>
                      <Input size="sm" type="url" placeholder="https://…" value={link.url} onChange={(e) => setLink({ ...link, url: e.target.value })} />
                      <Textarea rows={3} placeholder="Why it matters (optional): what to pull out of it" value={link.text} onChange={(e) => setLink({ ...link, text: e.target.value })} />
                      <Text fontSize="xs" color="muted">The page is fetched at ingest time, so the wiki records it as it was then.</Text>
                      <Button type="submit" size="sm" colorScheme="purple" alignSelf="start" isDisabled={!link.url.trim()}>Save link</Button>
                    </Stack>
                  </form>
                </TabPanel>
              </TabPanels>
            </Tabs>
          </Section>
          <Section title={`Waiting in _raw/ · ${items.length}`}>
            {inbox.error ? <Text color="red.400">{inbox.error}</Text> : !inbox.data ? <Loading /> : (
              <DataTable empty="Nothing waiting. Add something above." head={['File', 'Size', 'Added', '']} rows={items.map((it) => [
                it.text && it.name.endsWith('.md') ? <Link href={pageHref(it.path)}>{it.name}</Link> : <Text>{it.name}</Text>,
                <Text whiteSpace="nowrap" color="muted">{it.size < 1024 ? `${it.size} B` : `${Math.round(it.size / 1024)} KB`}</Text>,
                <Text whiteSpace="nowrap" color="muted">{it.modified.slice(0, 10)}</Text>,
                <Button size="xs" variant="ghost" colorScheme="red" leftIcon={<Trash2 size={12} />}
                  onClick={async () => { if (window.confirm(`Delete ${it.name} from _raw/?`)) { await api.post('/v1/inbox/remove', { name: it.name }); refresh() } }}>Remove</Button>,
              ])} />
            )}
          </Section>
        </Stack>
      </Body>
    </>
  )
}

// --- agent jobs --------------------------------------------------------------

function useJobs() {
  const [state, setState] = useState(null)
  const load = () => api.get('/v1/jobs').then(setState).catch(() => {})
  useEffect(() => { load() }, [])
  const running = state?.jobs.some((j) => j.status === 'running')
  // Poll only while something runs; a finished job needs no traffic.
  useEffect(() => {
    if (!running) return
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [running])
  return [state, load]
}

async function runJob(task, toast) {
  try {
    const job = await api.post('/v1/jobs', { task })
    toast({ status: 'info', title: `${job.label} started`, description: 'Claude Code is working on the vault. Follow it under Actions.' })
    return job
  } catch (e) {
    toast({ status: 'error', title: 'Could not start', description: e.message })
    return null
  }
}

function IngestButton({ disabled, onDone }) {
  const toast = useToast()
  const [jobs, reload] = useJobs()
  const running = jobs?.jobs.find((j) => j.task === 'ingest' && j.status === 'running')
  const was = useRef(false)
  useEffect(() => { if (was.current && !running) onDone?.(); was.current = Boolean(running) }, [running])
  if (jobs && !jobs.agent) return <Text fontSize="xs" color="muted" maxW="64">Run <Code fontSize="xs">/wiki-ingest</Code> in your agent to ingest these.</Text>
  return (
    <Button size="sm" colorScheme="purple" leftIcon={running ? <Spinner size="xs" /> : <Play size={14} />} isDisabled={disabled || Boolean(running)}
      onClick={async () => { if (await runJob('ingest', toast)) reload() }}>
      {running ? 'Ingesting…' : 'Ingest now'}
    </Button>
  )
}

const jobColor = { running: 'purple', done: 'green', failed: 'red' }

function NextActionList({ actions, compact }) {
  const toast = useToast()
  const { reload } = useVault()
  if (!actions.length) return <Text fontSize="sm" color="muted">Nothing needs doing. The vault is in good shape.</Text>
  const sync = async () => {
    if (!window.confirm('Commit every vault change and push it to the remote?')) return
    try { toast({ status: 'success', title: (await api.post('/v1/git/sync', {})).message }); reload() } catch (e) { toast({ status: 'error', title: 'Sync failed', description: e.message }) }
  }
  return (
    <Stack spacing="3">{actions.map((a) => (
      <Flex key={a.id} gap="3" align="center" wrap={compact ? 'nowrap' : 'wrap'}>
        <Box flex="1" minW="0">
          <Text fontSize="sm" fontWeight="medium">{a.title}</Text>
          <Text fontSize="xs" color="muted" noOfLines={2}>{a.detail}</Text>
        </Box>
        {a.job && <Button size="xs" colorScheme="purple" variant="outline" leftIcon={<Play size={12} />} onClick={() => runJob(a.job, toast).then((j) => j && go('/actions'))}>Run</Button>}
        {a.go && <Button size="xs" variant="outline" rightIcon={<ArrowRight size={12} />} onClick={() => go(a.go)}>Open</Button>}
        {a.sync && <Button size="xs" variant="outline" onClick={sync}>Sync</Button>}
      </Flex>
    ))}</Stack>
  )
}

export function NextActions() {
  const { status, todos } = useVault()
  const health = useFetch('/v1/health')
  return <NextActionList compact actions={nextActions({ status, todos, lint: health.data?.lint })} />
}

export function ActionsView() {
  const { status, todos } = useVault()
  const health = useFetch('/v1/health')
  const [jobs, reload] = useJobs()
  const toast = useToast()
  return (
    <>
      <Header title="Actions" description="What the vault needs next, and wiki skills you can run from here. Jobs run Claude Code on this machine, using your Claude subscription." />
      <Body>
        <Stack spacing="4" maxW="5xl">
          <Section title="Next up">
            {!status ? <Loading /> : <NextActionList actions={nextActions({ status, todos, lint: health.data?.lint })} />}
          </Section>
          <Section title="Run a skill">
            {!jobs ? <Loading /> : (
              <>
                {!jobs.agent && <Alert status="info" mb="4" borderRadius="md"><AlertIcon /><AlertDescription fontSize="sm">Claude Code isn't on this machine's PATH, so jobs can't run here. Copy a command into any agent that has the wiki skills.</AlertDescription></Alert>}
                <SimpleGrid columns={{ base: 1, md: 2 }} spacing="3">{jobs.tasks.map((t) => {
                  const running = jobs.jobs.some((j) => j.task === t.task && j.status === 'running')
                  return (
                    <Flex key={t.task} borderWidth="1px" borderRadius="md" p="3" gap="3" align="center">
                      <Box flex="1" minW="0"><Text fontWeight="medium" fontSize="sm">{t.label}</Text><Code fontSize="xs" noOfLines={1} title={t.prompt}>{t.prompt}</Code></Box>
                      {jobs.agent
                        ? <Button size="sm" colorScheme="purple" isLoading={running} leftIcon={<Play size={14} />} onClick={async () => { if (await runJob(t.task, toast)) reload() }}>Run</Button>
                        : <Button size="sm" variant="outline" onClick={() => navigator.clipboard.writeText(t.prompt)}>Copy</Button>}
                    </Flex>
                  )
                })}</SimpleGrid>
              </>
            )}
          </Section>
          <Section title="Recent jobs">
            {!jobs?.jobs.length ? <Text fontSize="sm" color="muted">No jobs yet this session.</Text> : (
              <Stack spacing="3">{jobs.jobs.map((j) => (
                <Box key={j.id} borderWidth="1px" borderRadius="md" p="3">
                  <HStack>
                    <Badge colorScheme={jobColor[j.status]}>{j.status}</Badge>
                    <Text fontWeight="medium" fontSize="sm">{j.label}</Text>
                    {j.status === 'running' && <Spinner size="xs" />}
                    <Text ms="auto" fontSize="xs" color="muted">{j.started.slice(11, 16)} UTC{j.cost_usd != null && ` · $${j.cost_usd.toFixed(2)}`}</Text>
                  </HStack>
                  {j.output && <Box mt="2" fontSize="sm" maxH="80" overflowY="auto"><Markdown text={j.output} /></Box>}
                </Box>
              ))}</Stack>
            )}
          </Section>
        </Stack>
      </Body>
    </>
  )
}

// --- ask: answers grounded in the vault, optionally the web ---------------------

export function AskView({ params }) {
  const settings = useFetch('/v1/settings')
  const insights = useFetch('/v1/insights')
  const { index, reload } = useVault()
  const [q, setQ] = useState(params.get('q') ?? '')
  const [web, setWeb] = useState(null)
  const [thread, setThread] = useState([])
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  const useWeb = web ?? settings.data?.web ?? true
  const askIt = async (question) => {
    if (!question.trim() || busy) return
    setBusy(true)
    setThread((t) => [{ question, pending: true }, ...t])
    try {
      const r = await api.post('/v1/ask', { question, web: useWeb })
      setThread((t) => [{ question, ...r }, ...t.slice(1)])
      setQ('')
    } catch (e) {
      setThread((t) => [{ question, error: e.message }, ...t.slice(1)])
    } finally { setBusy(false) }
  }
  useEffect(() => { if (params.get('q') && settings.data?.active_provider) askIt(params.get('q')) }, [settings.data])
  const keep = async (turn) => {
    await api.post('/v1/inbox', { kind: 'text', title: `Answer: ${turn.question}`, text: `**Question:** ${turn.question}\n\n${turn.answer}` })
    toast({ status: 'success', title: 'Saved to the inbox', description: 'The next ingest files it as a synthesis page.' })
    reload()
  }
  if (settings.error) return <ErrorState message={settings.error} />
  if (!settings.data) return <Loading />
  const s = settings.data
  return (
    <>
      <Header title="Ask your wiki" description="Answers come from your own pages, cited, with the gaps called out. Turn on the web to fill those gaps." />
      <Body>
        <Stack spacing="4" maxW="4xl">
          {!s.active_provider && (
            <Alert status="warning" borderRadius="md"><AlertIcon />
              <AlertDescription fontSize="sm">No model is set up. Install Claude Code to use your Claude subscription, or <Link href="#/settings" textDecoration="underline">add an Anthropic API key</Link>.</AlertDescription>
            </Alert>
          )}
          <form onSubmit={(e) => { e.preventDefault(); askIt(q) }}>
            <Stack>
              <InputGroup size="lg">
                <Input placeholder="What did I decide about…? What do I know about…?" value={q} onChange={(e) => setQ(e.target.value)} isDisabled={!s.active_provider} pr="14" />
                <InputRightElement><Button type="submit" size="sm" colorScheme="purple" isLoading={busy} isDisabled={!q.trim() || !s.active_provider} aria-label="Ask"><Send size={14} /></Button></InputRightElement>
              </InputGroup>
              <HStack fontSize="sm" color="muted" spacing="4">
                <HStack as="label" spacing="2"><Switch size="sm" colorScheme="purple" isChecked={useWeb} onChange={(e) => setWeb(e.target.checked)} /><Globe size={14} /><span>Search the web too</span></HStack>
                <Text ms="auto" fontSize="xs">via {s.active_provider === 'claude-cli' ? 'Claude Code (your subscription)' : s.active_provider === 'anthropic' ? 'Anthropic API key' : '—'}</Text>
              </HStack>
            </Stack>
          </form>
          {!thread.length && insights.data?.suggested_questions?.length > 0 && (
            <Section title="Questions your graph raises">
              <Stack spacing="2">{insights.data.suggested_questions.slice(0, 5).map((sq) => (
                <Button key={sq.question} variant="ghost" size="sm" justifyContent="start" whiteSpace="normal" textAlign="left" h="auto" py="2" fontWeight="normal"
                  leftIcon={<Sparkles size={14} />} onClick={() => askIt(sq.question.replace(/`/g, ''))} isDisabled={!s.active_provider}>{sq.question.replace(/`/g, '')}</Button>
              ))}</Stack>
            </Section>
          )}
          {thread.map((t, i) => (
            <Section key={thread.length - i} title={t.question}>
              {t.pending ? <HStack color="muted" fontSize="sm"><Spinner size="sm" /><Text>Reading your vault{useWeb ? ' and the web' : ''}…</Text></HStack>
                : t.error ? <Text color="red.400" fontSize="sm">{t.error}</Text> : (
                  <>
                    <Markdown text={t.answer} />
                    <Flex mt="4" gap="3" align="center" wrap="wrap" borderTopWidth="1px" pt="3">
                      <Text fontSize="xs" color="muted">Read {t.pages.length} page{t.pages.length === 1 ? '' : 's'}:</Text>
                      <Wrap spacing="2" flex="1">{t.pages.slice(0, 8).map((p) => <WrapItem key={p.path}><Link href={pageHref(p.path)} fontSize="xs">{p.title || nameOf(index, p.path)}</Link></WrapItem>)}</Wrap>
                      <Button size="xs" variant="outline" onClick={() => keep(t)}>Save to inbox</Button>
                    </Flex>
                  </>
                )}
            </Section>
          ))}
        </Stack>
      </Body>
    </>
  )
}

// --- insights: what the link graph says about the vault --------------------------

export function InsightsView() {
  const ins = useFetch('/v1/insights')
  const { index } = useVault()
  const toast = useToast()
  if (ins.error) return <ErrorState message={ins.error} />
  if (!ins.data || !index) return <Loading />
  const d = ins.data
  if (!d.stats.pages) return <EmptyState title="No graph yet" description="Ingest a few sources and the structure shows up here." py="16" />
  const page = (id) => {
    const n = index.byId.get(id)
    return n ? <Link href={pageHref(n.path)}>{n.title || nameOf(index, n.path)}</Link> : <Text as="span">{id}</Text>
  }
  const stat = (label, n) => <Box borderWidth="1px" borderRadius="md" p="3"><Stat><StatLabel color="muted">{label}</StatLabel><StatNumber fontSize="xl">{n}</StatNumber></Stat></Box>
  const lonely = [...new Set([...d.isolated, ...d.dead_ends])]
  return (
    <>
      <Header title="Insights" description="Hubs, bridges, clusters and blind spots in your knowledge graph, computed from the wikilinks." />
      <Body>
        <SimpleGrid columns={{ base: 2, md: 4 }} spacing="3" mb="4">
          {stat('Pages', d.stats.pages)}{stat('Links', d.stats.edges)}{stat('Clusters', d.stats.communities)}{stat('Pages with no way out', lonely.length)}
        </SimpleGrid>
        <SimpleGrid columns={{ base: 1, xl: 2 }} spacing="4">
          <Section title="Questions worth asking">
            <Stack spacing="3">{d.suggested_questions.slice(0, 6).map((sq) => (
              <Box key={sq.question}>
                <Link fontSize="sm" fontWeight="medium" href={`#/ask?q=${encodeURIComponent(sq.question.replace(/`/g, ''))}`}>{sq.question.replace(/`/g, '')}</Link>
                <Text fontSize="xs" color="muted">{sq.why}</Text>
              </Box>
            ))}</Stack>
          </Section>
          <Section title="Bridges: pages that hold clusters together">
            <DataTable head={['Page', 'Links clusters', 'Betweenness']} rows={d.bridges.map((b) => [page(b.page), b.connects.length, b.betweenness.toFixed(2)])} />
          </Section>
          <Section title="Unexpected connections">
            <Stack spacing="2">{d.surprising_connections.slice(0, 8).map((c) => (
              <Text key={c.source + c.target} fontSize="sm">{page(c.source)} <Text as="span" color="muted">↔</Text> {page(c.target)}</Text>
            ))}</Stack>
          </Section>
          <Section title="Hubs">
            <DataTable head={['Page', 'Backlinks', 'Links out']} rows={d.god_nodes.slice(0, 8).map((g) => [page(g.page), g.in_degree, g.out_degree])} />
          </Section>
          <Section title="Clusters" gridColumn={{ xl: 'span 2' }}>
            <Stack spacing="3">{d.communities.filter((c) => c.size > 1).slice(0, 10).map((c) => (
              <Box key={c.id}>
                <HStack><Text fontWeight="medium" fontSize="sm">{c.label}</Text><Badge>{c.size} pages</Badge><Text fontSize="xs" color="muted">cohesion {c.cohesion.toFixed(2)}</Text></HStack>
                <Text fontSize="xs" color="muted" noOfLines={2}>{c.pages.slice(0, 12).map((p) => index.byId.get(p)?.title || p).join(' · ')}</Text>
              </Box>
            ))}</Stack>
          </Section>
          {lonely.length > 0 && (
            <Section title="Blind spots" gridColumn={{ xl: 'span 2' }}>
              <Text fontSize="sm" color="muted" mb="3">These pages link nowhere or nothing links to them, so a search walk can't reach them.</Text>
              <Wrap spacing="3" mb="3">{lonely.slice(0, 30).map((id) => <WrapItem key={id} fontSize="sm">{page(id)}</WrapItem>)}</Wrap>
              <Button size="sm" variant="outline" leftIcon={<Play size={14} />} onClick={() => runJob('cross-link', toast)}>Run cross-linker</Button>
            </Section>
          )}
        </SimpleGrid>
      </Body>
    </>
  )
}

// --- settings ----------------------------------------------------------------------

export function SettingsView() {
  const [tick, setTick] = useState(0)
  const st = useFetch('/v1/settings', [tick])
  const [key, setKey] = useState('')
  const toast = useToast()
  const save = async (patch, message = 'Saved') => {
    try { await api.post('/v1/settings', patch); setTick((t) => t + 1); toast({ status: 'success', title: message }) } catch (e) { toast({ status: 'error', title: 'Not saved', description: e.message }) }
  }
  if (st.error) return <ErrorState message={st.error} />
  if (!st.data) return <Loading />
  const s = st.data
  const yes = (ok, label) => <Badge colorScheme={ok ? 'green' : 'gray'}>{ok ? label : 'not found'}</Badge>
  return (
    <>
      <Header title="Settings" description="How Ask and the agent jobs reach a model. Stored on this machine (outside the vault), never sent to the browser." />
      <Body>
        <Stack spacing="4" maxW="3xl">
          <Section title="Model">
            <Stack spacing="5">
              <FormControl>
                <FormLabel fontSize="sm">Provider</FormLabel>
                <Select size="sm" value={s.provider} onChange={(e) => save({ provider: e.target.value })}>
                  <option value="auto">Automatic: Claude Code if installed, else the API key</option>
                  <option value="claude-cli">Claude Code CLI (your Claude subscription)</option>
                  <option value="anthropic">Anthropic API key</option>
                </Select>
                <FormHelperText>In use now: <b>{s.active_provider === 'claude-cli' ? 'Claude Code' : s.active_provider === 'anthropic' ? 'Anthropic API' : 'none'}</b>. Agent jobs (ingest, lint, cross-link) always need Claude Code, because they edit files.</FormHelperText>
              </FormControl>
              <HStack fontSize="sm" spacing="6" wrap="wrap">
                <HStack><Text>Claude Code</Text>{yes(s.claude_cli, 'installed')}</HStack>
                <HStack><Text>Anthropic SDK</Text>{yes(s.sdk_installed, 'installed')}</HStack>
              </HStack>
              <FormControl>
                <FormLabel fontSize="sm">Anthropic API key</FormLabel>
                <form onSubmit={(e) => { e.preventDefault(); if (key.trim()) save({ anthropic_api_key: key.trim() }, 'Key saved').then(() => setKey('')) }}>
                  <HStack>
                    <Input size="sm" type="password" autoComplete="off" placeholder={s.anthropic_key_set ? `Saved (${s.anthropic_key_hint || 'set'})` : 'sk-ant-…'} value={key} onChange={(e) => setKey(e.target.value)} />
                    <Button size="sm" type="submit" colorScheme="purple" isDisabled={!key.trim()}>Save</Button>
                    {s.anthropic_key_set && !s.anthropic_key_from_env && <Button size="sm" variant="ghost" colorScheme="red" onClick={() => save({ anthropic_api_key: '' }, 'Key removed')}>Remove</Button>}
                  </HStack>
                </form>
                <FormHelperText>{s.anthropic_key_from_env ? 'Using ANTHROPIC_API_KEY from the environment.' : 'Billed to your API account. Get one at console.anthropic.com.'}</FormHelperText>
              </FormControl>
              <FormControl>
                <FormLabel fontSize="sm">Model</FormLabel>
                <Input size="sm" defaultValue={s.model} placeholder={`Default: ${s.default_api_model} for the API, your Claude Code default for the CLI`}
                  onBlur={(e) => e.target.value !== s.model && save({ model: e.target.value })} />
                <FormHelperText>Optional. A model ID such as claude-sonnet-5-5, or a Claude Code alias such as sonnet or opus.</FormHelperText>
              </FormControl>
              <FormControl display="flex" alignItems="center" gap="3">
                <Switch colorScheme="purple" isChecked={s.web} onChange={(e) => save({ web: e.target.checked })} />
                <FormLabel fontSize="sm" m="0">Search the web from Ask by default</FormLabel>
              </FormControl>
            </Stack>
          </Section>
          <Section title="Run it yourself">
            <Text fontSize="sm" color="muted" mb="2">Everything here is also a skill in your agent:</Text>
            <CodeBlock lang="text" code={'/wiki-ingest          # process the inbox (_raw/)\n/wiki-query <question> # ask with citations\n/wiki-research <topic> # discover sources on the web\n/wiki-lint            # fix broken links and frontmatter'} />
          </Section>
        </Stack>
      </Body>
    </>
  )
}
