import React from 'react';
import { MovieOttProvider } from '../../api/client.ts';

export function isPresetSearchLabel(value: string): boolean {
  const normalized = String(value || '').trim().toLowerCase().replace(/\s+/g, ' ');
  return new Set([
    'bollywood movies',
    'marvel movies (english)',
    'marvel movies (hindi)',
    'dc live-action movies (english)',
    'dc live-action movies (hindi)',
    'dc animated movies',
  ]).has(normalized);
}


export function providerNames(providers: MovieOttProvider[]): React.ReactNode {
  const shown = providers.slice(0, 3);
  return (
    <>
      {shown.map((provider, index) => (
        <React.Fragment key={String(provider.providerId ?? provider.name) + '-' + index}>
          {index > 0 ? ', ' : ''}
          {provider.webUrl ? (
            <a href={provider.webUrl} target="_blank" rel="noreferrer" className="text-cyan-300 underline underline-offset-2 hover:text-cyan-200">
              {provider.name}
            </a>
          ) : provider.name}
        </React.Fragment>
      ))}
      {providers.length > 3 ? ' +' + (providers.length - 3) : ''}
    </>
  );
}


export function formatPublished(value?: string) {
  if (!value) return 'Unknown date';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Unknown date';
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}
