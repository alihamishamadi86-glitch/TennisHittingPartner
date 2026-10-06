import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];

export type ClientProfile = Schemas["ClientProfileOut"];
export type ClientProfileInput = Schemas["ClientProfileIn"];
export type PartnerProfile = Schemas["PartnerProfileOut"];
export type PartnerProfileInput = Schemas["PartnerProfileIn"];
export type DominantHand = Schemas["DominantHand"];
export type PlayStyle = Schemas["PlayStyle"];
export type ClientGoal = Schemas["ClientGoal"];
export type PartnerBackground = Schemas["PartnerBackground"];
export type PartnerStatus = Schemas["PartnerStatus"];
export type Question = Schemas["QuestionOut"];
export type PartnerApplication = Schemas["PartnerApplicationOut"];
export type PartnerApplicationDetail = Schemas["PartnerApplicationDetailOut"];
