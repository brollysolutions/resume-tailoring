import { render, screen, waitFor } from '@testing-library/react'
import Page from '../app/page'
import JobSearchPage from '../app/job-search/page'
import TailorPage from '../app/tailor/page'

// Mock next/navigation
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: jest.fn(),
  }),
  useSearchParams: () => ({
    get: jest.fn(),
  }),
}))

// Mock framer-motion to avoid animation issues in tests
jest.mock('framer-motion', () => ({
  motion: {
    div: ({ children, ...props }: any) => <div {...props}>{children}</div>,
    h1: ({ children, ...props }: any) => <h1 {...props}>{children}</h1>,
    p: ({ children, ...props }: any) => <p {...props}>{children}</p>,
    button: ({ children, ...props }: any) => <button {...props}>{children}</button>,
  },
  AnimatePresence: ({ children }: any) => <div>{children}</div>,
}))

describe('Smoke Tests', () => {
  it('renders the landing page', async () => {
    render(<Page />)
    expect(screen.getByText(/Tailor your resume to any job/i)).toBeInTheDocument()
  })

  it('renders the job search page', async () => {
    // Set current_resume_id in localStorage to avoid redirect
    Storage.prototype.getItem = jest.fn((key) => {
      if (key === 'current_resume_id') return 'test-id'
      return null
    })
    
    render(<JobSearchPage />)
    expect(screen.getByText(/Match a job/i)).toBeInTheDocument()
  })

  it('renders the tailor page', async () => {
     // Set context in localStorage
     Storage.prototype.getItem = jest.fn((key) => {
      if (key === 'current_resume_id') return 'test-id'
      if (key === 'tailor_jd_text') return 'test jd text'
      return null
    })

    render(<TailorPage />)
    await waitFor(() => {
        expect(screen.getByText(/Tailor your resume/i)).toBeInTheDocument()
    })
  })
})