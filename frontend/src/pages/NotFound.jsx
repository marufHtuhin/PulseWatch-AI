import { Link } from 'react-router-dom'
import { Compass } from 'lucide-react'
import { EmptyState } from '../components/Cards'

export function NotFound() {
  return (
    <EmptyState
      icon={Compass}
      title="Page not found"
      description="The page you're looking for doesn't exist or was moved."
      action={
        <Link to="/" className="btn-primary">
          Back to Dashboard
        </Link>
      }
    />
  )
}
