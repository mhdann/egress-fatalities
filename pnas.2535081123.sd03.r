# ============================================
# Segmented Regression of Cumulative Fatalities
# ============================================

#-----------------------------
# 1. Load libraries
#-----------------------------
library(dplyr)
library(ggplot2)
library(segmented)
library(GGally)

#-----------------------------
# 2. Load and clean data
#-----------------------------
fatalities <- read.csv("~/papers/roads/fire-fatality-for-R.csv") # change this filepath to your local machine

fatalities_clean <- fatalities %>%
  filter(!is.na(Identified.fatalities), !is.na(exits), !is.na(population)) %>%
  mutate(
    Identified.fatalities = as.numeric(Identified.fatalities),
    population = as.numeric(population),
    per_fatal = Identified.fatalities / population * 100,
    # NEW: percentile rank of exits (0–100 scale)
    exits_pct = percent_rank(exits) * 100
  ) %>%
  filter(!is.na(per_fatal), !is.na(exits)) %>%
  arrange(exits) %>%
  mutate(cum_per_fatal = sum(per_fatal) - cumsum(per_fatal))

#-----------------------------
# 3. Segmented regression (raw exits)
#-----------------------------
lm_fit_raw <- lm(cum_per_fatal ~ exits, data = fatalities_clean)
seg_fit_raw <- segmented(lm_fit_raw)
bp_raw <- seg_fit_raw$psi[2]

#-----------------------------
# 4. Segmented regression (percentile exits)
#-----------------------------
lm_fit_pct <- lm(cum_per_fatal ~ exits_pct, data = fatalities_clean)
seg_fit_pct <- segmented(lm_fit_pct)
bp_pct <- seg_fit_pct$psi[2]

#-----------------------------
# 5. Predictions for plotting
#-----------------------------
pred_grid_raw <- data.frame(
  exits = seq(min(fatalities_clean$exits), max(fatalities_clean$exits), length.out = 400)
)
pred_grid_raw$fit <- predict(seg_fit_raw, newdata = pred_grid_raw)

pred_grid_pct <- data.frame(
  exits_pct = seq(min(fatalities_clean$exits_pct), max(fatalities_clean$exits_pct), length.out = 400)
)
pred_grid_pct$fit <- predict(seg_fit_pct, newdata = pred_grid_pct)

#-----------------------------
# 6. Plot side-by-side (optional)
#-----------------------------
library(patchwork)

p1 <- ggplot(fatalities_clean, aes(x = exits, y = cum_per_fatal)) +
  geom_point(size = 2, alpha = 0.6) +
  geom_line(data = pred_grid_raw, aes(x = exits, y = fit), color = "red", size = 1) +
  geom_vline(xintercept = bp_raw, linetype = "dashed") +
  labs(
    title = paste0("Raw exits (breakpoint ≈ ", round(bp_raw, 2), ")"),
    x = "Number of Exits",
    y = "Cumulative Fatality (%)"
  ) +
  theme_classic(base_size = 14)

p2 <- ggplot(fatalities_clean, aes(x = exits_pct, y = cum_per_fatal)) +
  geom_point(size = 2, alpha = 0.6) +
  geom_line(data = pred_grid_pct, aes(x = exits_pct, y = fit), color = "red", size = 1) +
  geom_vline(xintercept = bp_pct, linetype = "dashed") +
  labs(
    title = paste0("Exit percentile (breakpoint ≈ ", round(bp_pct, 1), "th percentile)"),
    x = "Exit Percentile (0 = fewest exits, 100 = most)",
    y = "Cumulative Fatality (%)"
  ) +
  theme_classic(base_size = 14)

p1 + p2

sorted_exits <- sort(fatalities_clean$exits)
# Convert percentile back to index
p <- 0.666        # 66.6th percentile
n <- nrow(fatalities_clean)
idx <- ceiling(p * (n - 1)) + 1

real_exit_number <- sorted_exits[idx]
real_exit_number




# ============================================
# Additional relationships
# ============================================

# Create per-capita fatality rate
fatalities_clean <- fatalities_clean %>%
  mutate(per_capita_fatality = Fatalities / population)

# ---------------------------------------------
# 1. Raw Fatalities vs Number of Exits
# ---------------------------------------------
p1 <- ggplot(fatalities_clean, aes(x = exits, y = Identified.fatalities)) +
  geom_point(aes(size = population), alpha = 0.7, color = "steelblue") +
  geom_smooth(method = "lm", se = TRUE, color = "darkred") +
  scale_size_continuous(name = "Population") +
  labs(
    x = "Number of Egress Roads",
    y = "Fatalities (#)",
    title = "Raw Fatalities vs Number of Exits"
  ) +
  theme_classic()

lm1 <- lm(Identified.fatalities ~ exits, data = fatalities_clean)
summary(lm1)


# ---------------------------------------------
# 2. Population vs Number of Exits
# ---------------------------------------------
p2 <- ggplot(fatalities_clean, aes(x = population, y = exits)) +
  geom_point(alpha = 0.7, color = "forestgreen") +
  geom_smooth(method = "lm", se = TRUE, color = "darkorange") +
  labs(
    x = "Population",
    y = "Number of Egress Roads",
    title = "Relationship Between Population and Number of Exits"
  ) +
  theme_classic()

lm2 <- lm(population ~ exits, data = fatalities_clean)
summary(lm2)

# ---------------------------------------------
# 3. Per-capita Fatality Rate vs Number of Exits
# ---------------------------------------------
fatalities_clean <- fatalities_clean %>%
  filter(!is.na(per_capita_fatality), !is.na(exits))


p3 <- ggplot(fatalities_clean, aes(x = exits, y = per_capita_fatality, size = population)) +
  geom_point(alpha = 0.7, color = "purple") +
  geom_smooth(method = "lm", se = TRUE, color = "red") +
  scale_size_continuous(name = "Population") +
  labs(
    x = "Number of Egress Roads",
    y = "Per-capita Fatality Rate",
    title = "Per-capita Fatality Rate vs Number of Exits"
  ) +
  theme_classic()

lm3 <- lm(per_capita_fatality ~ exits, data = fatalities_clean)
summary(lm3)


# ---------------------------------------------
# 4. Population-weighted Fatality Rate vs Exits
#    - Here, weight by population to see robustness
# ---------------------------------------------
p4 <- ggplot(fatalities_clean, aes(x = exits, y = per_capita_fatality, weight = population)) +
  geom_point(alpha = 0.6, color = "darkcyan") +
  geom_smooth(method = "lm", se = TRUE, color = "darkred") +
  labs(
    x = "Number of Egress Roads",
    y = "Per-capita Fatality Rate (Population-weighted)",
    title = "Population-weighted Fatality Rate vs Number of Exits"
  ) +
  theme_classic()

lm_weighted <- lm(per_capita_fatality ~ exits, data = fatalities_clean, weights = population)
summary(lm_weighted)



# ---------------------------------------------
# 6. Pairwise Plot (correlations)
# ---------------------------------------------
# Select key numeric variables
fatality_vars <- fatalities_clean  %>%
  dplyr::select(Fatalities, per_capita_fatality, population, exits)

p6 <- ggpairs(fatality_vars,
              upper = list(continuous = wrap("cor", size = 3)),
              lower = list(continuous = wrap("points", alpha = 0.6, size = 2)),
              diag = list(continuous = wrap("densityDiag"))
)

