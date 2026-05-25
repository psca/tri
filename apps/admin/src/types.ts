export type AthleteView = {
  athlete_id: string;
  name: string;
  bib_number: string | null;
  next_event_id: string | null;
  status: string;
};

export type AcceptedEventView = {
  athlete_id: string;
  route_event_id: string;
  checkpoint_id: string;
  timestamp: string;
  confidence: string;
};

export type RaceStateView = {
  race_id: string;
  phase: string;
  athletes: AthleteView[];
  accepted_events: AcceptedEventView[];
  warnings: string[];
};
