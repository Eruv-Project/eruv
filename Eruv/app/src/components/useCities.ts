// The public city list (GET /api/cities), for the pickers and the admin switcher.
import { useCallback, useEffect, useState } from 'react';

import { api, type CityName } from '../api/client';

export function useCities() {
  const [cities, setCities] = useState<CityName[] | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    setError(false);
    try {
      setCities(await api.cities());
    } catch {
      setError(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return { cities, error, reload: load };
}
