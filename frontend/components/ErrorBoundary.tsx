'use client';

import React, { ReactNode } from 'react';

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback || (
          <div
            role="alert"
            aria-live="assertive"
            className="min-h-screen flex items-center justify-center bg-subtle p-4"
          >
            <div className="max-w-md w-full space-y-4 card p-6 shadow">
              <h1 className="text-xl font-semibold text-danger">Something went wrong</h1>
              <p className="text-sm text-muted">
                {this.state.error?.message || 'An unexpected error occurred. Please reload the page.'}
              </p>
              <button
                onClick={() => window.location.reload()}
                className="btn-primary w-full"
              >
                Reload page
              </button>
            </div>
          </div>
        )
      );
    }

    return this.props.children;
  }
}
