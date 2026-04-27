import React, { useState } from 'react'
import ProjectList from './components/ProjectList'
import Editor from './components/Editor'

export default function App() {
  const [projectId, setProjectId] = useState<number | null>(null)

  if (projectId) {
    return <Editor projectId={projectId} onBack={() => setProjectId(null)} />
  }
  return <ProjectList onOpen={setProjectId} />
}
