import { reactive } from 'vue'
import { api } from '../api'
import { errorText, toast } from '../store'
import type { DirEntry, DirSummary } from '../types'

interface NodeState {
  expanded: boolean
  loading: boolean
  children?: DirEntry[]
  shown: number
}

// Huge folders render their children in pages so the DOM stays small.
export const PAGE_SIZE = 500

// Expansion state shared by the sidebar tree and the folder picker.
export const tree = reactive({
  roots: [] as DirEntry[],
  nodes: {} as Record<string, NodeState>,
  summaries: {} as Record<string, DirSummary>,
})

const nodeState = (path: string) => (tree.nodes[path] ??= { expanded: false, loading: false, shown: PAGE_SIZE })

export async function loadRoots() {
  try {
    tree.roots = (await api.browse('')).dirs
  } catch (e) {
    toast(errorText(e), 'error')
  }
}

async function loadChildren(path: string) {
  const node = nodeState(path)
  node.loading = true
  try {
    node.children = (await api.browse(path)).dirs
    node.shown = PAGE_SIZE
    const known = tree.summaries[path]
    tree.summaries[path] = { audio: known?.audio ?? 0, has_children: node.children.length > 0 }
  } catch (e) {
    node.children = []
    toast(errorText(e), 'error')
  } finally {
    node.loading = false
  }
}

export async function toggle(path: string) {
  const node = nodeState(path)
  node.expanded = !node.expanded
  if (node.expanded && !node.children) await loadChildren(path)
}

export function showMore(path: string) {
  nodeState(path).shown += PAGE_SIZE
}

function visiblePaths() {
  const paths: string[] = []
  const walk = (dirs: DirEntry[]) => {
    for (const dir of dirs) {
      paths.push(dir.path)
      const node = tree.nodes[dir.path]
      if (node?.expanded && node.children) walk(node.children.slice(0, node.shown))
    }
  }
  walk(tree.roots)
  return paths
}

/**
 * Apply an arrow key to the tree and return the folder that should be active next.
 * Right expands a folder, then moves into it. Left collapses a folder, then moves to its parent.
 * Returns undefined for any other key.
 */
export function navigate(path: string, key: string): string | undefined {
  const paths = visiblePaths()
  const index = paths.indexOf(path)
  if (index < 0) return key.startsWith('Arrow') ? paths[0] : undefined
  const node = tree.nodes[path]
  switch (key) {
    case 'ArrowUp':
      return paths[Math.max(0, index - 1)]
    case 'ArrowDown':
      return paths[Math.min(paths.length - 1, index + 1)]
    case 'ArrowRight':
      if (!node?.expanded) {
        if (tree.summaries[path]?.has_children ?? true) void toggle(path)
        return path
      }
      return node.children?.length ? paths[index + 1] : path
    case 'ArrowLeft': {
      if (node?.expanded) {
        void toggle(path)
        return path
      }
      const parent = path.slice(0, path.lastIndexOf('/'))
      return paths.includes(parent) ? parent : path
    }
  }
}

/**
 * Expand every ancestor of a path so it becomes visible.
 */
export async function reveal(path: string) {
  const root = tree.roots.find((r) => path === r.path || path.startsWith(r.path + '/'))
  if (!root) return
  const parts = path.slice(root.path.length).split('/').filter(Boolean)
  let current = root.path
  for (const part of parts) {
    const node = nodeState(current)
    if (!node.children) await loadChildren(current)
    node.expanded = true
    const index = node.children?.findIndex((c) => c.name === part) ?? -1
    if (index >= node.shown) node.shown = index + 1
    current = `${current}/${part}`
  }
}

/**
 * Re-read every expanded folder after files were moved.
 */
export async function refreshTree() {
  await loadRoots()
  const expanded = Object.entries(tree.nodes)
    .filter(([, n]) => n.children)
    .map(([p]) => p)
  tree.summaries = {}
  await Promise.all(
    expanded.map(async (p) => {
      try {
        tree.nodes[p].children = (await api.browse(p)).dirs
      } catch {
        delete tree.nodes[p]
      }
    }),
  )
}

// --- summaries -------------------------------------------------------------------

// Track counts and expand arrows are fetched in batches, only for folders that
// are on screen, so opening a folder with thousands of subfolders stays instant.
const BATCH_SIZE = 100
const queued = new Set<string>()
const inflight = new Set<string>()
let flushing = false
let timer: ReturnType<typeof setTimeout> | undefined

export function requestSummary(path: string) {
  if (path in tree.summaries || inflight.has(path)) return
  queued.add(path)
  clearTimeout(timer)
  timer = setTimeout(flush, 40)
}

export function cancelSummary(path: string) {
  queued.delete(path)
}

async function flush() {
  if (flushing) return
  flushing = true
  try {
    while (queued.size) {
      const batch = [...queued].slice(0, BATCH_SIZE)
      for (const p of batch) {
        queued.delete(p)
        inflight.add(p)
      }
      try {
        const { summaries } = await api.browseSummary(batch)
        Object.assign(tree.summaries, summaries)
      } catch {
        // Failed folders stay unknown and are asked for again when they scroll back into view.
      } finally {
        for (const p of batch) inflight.delete(p)
      }
    }
  } finally {
    flushing = false
  }
}

const visibilityCallbacks = new WeakMap<Element, (visible: boolean) => void>()
let observer: IntersectionObserver | undefined

export function observeVisibility(el: Element, callback: (visible: boolean) => void) {
  observer ??= new IntersectionObserver(
    (entries) => {
      for (const e of entries) visibilityCallbacks.get(e.target)?.(e.isIntersecting)
    },
    { rootMargin: '300px 0px' },
  )
  visibilityCallbacks.set(el, callback)
  observer.observe(el)
}

export function unobserveVisibility(el: Element) {
  observer?.unobserve(el)
  visibilityCallbacks.delete(el)
}
