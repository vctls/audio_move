import { reactive } from 'vue'
import { api } from '../api'
import { errorText, toast } from '../store'
import type { DirEntry } from '../types'

interface NodeState {
  expanded: boolean
  loading: boolean
  children?: DirEntry[]
}

// Expansion state shared by the sidebar tree and the folder picker.
export const tree = reactive({
  roots: [] as DirEntry[],
  nodes: {} as Record<string, NodeState>,
})

export async function loadRoots() {
  try {
    tree.roots = (await api.browse('')).dirs
  } catch (e) {
    toast(errorText(e), 'error')
  }
}

async function loadChildren(path: string) {
  const node = (tree.nodes[path] ??= { expanded: false, loading: false })
  node.loading = true
  try {
    node.children = (await api.browse(path)).dirs
  } catch (e) {
    node.children = []
    toast(errorText(e), 'error')
  } finally {
    node.loading = false
  }
}

export async function toggle(path: string) {
  const node = (tree.nodes[path] ??= { expanded: false, loading: false })
  node.expanded = !node.expanded
  if (node.expanded && !node.children) await loadChildren(path)
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
    const node = (tree.nodes[current] ??= { expanded: false, loading: false })
    if (!node.children) await loadChildren(current)
    node.expanded = true
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
