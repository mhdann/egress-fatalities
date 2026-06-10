# ============================================
# Segmented Regression of Cumulative Fatalities
# ============================================

#-----------------------------
# 1. Load libraries
#-----------------------------
library(dplyr)        # data wrangling
library(ggplot2)      # plotting
library(segmented)    # segmented regression / breakpoint estimation

#-----------------------------
# 2. Load and clean data
#-----------------------------
fatalities <- read.csv("~/papers/roads/fire-fatality-for-R.csv") ## change this to be your machine's filepath

fatalities_clean <- fatalities %>%
  filter(!is.na(Identified.fatalities), !is.na(exits), !is.na(population)) %>%
  mutate(
    Identified.fatalities = as.numeric(Identified.fatalities),
    population = as.numeric(population),
    per_fatal = Identified.fatalities / population * 100
  ) %>%
  filter(!is.na(per_fatal), !is.na(exits)) %>%
  arrange(exits) %>%
  # cumulative fatalities (reversed for plotting, if desired)
  mutate(cum_per_fatal = sum(per_fatal) - cumsum(per_fatal))

#-----------------------------
# 3. Fit segmented regression
#-----------------------------
# Base linear model
lm_fit <- lm(cum_per_fatal ~ exits, data = fatalities_clean)

# Segmented (piecewise) model with one breakpoint
seg_fit <- segmented(lm_fit)

# Extract estimated breakpoint (x-value)
bp <- seg_fit$psi[2]

# Optional: check summary
summary(seg_fit)

#-----------------------------
# 4. Create prediction grid for plotting
#-----------------------------
pred_grid <- data.frame(
  exits = seq(min(fatalities_clean$exits),
              max(fatalities_clean$exits), length.out = 400)
)
pred_grid$fit <- predict(seg_fit, newdata = pred_grid)

#-----------------------------
# 5. Define background bins
#-----------------------------
# Customize breaks and labels
bins <- c(0, 5, 9, max(fatalities_clean$exits, na.rm = TRUE))
bin_labels <- c("Low", "Medium", "High")
bin_colors <- c("Low" = "#deebf7", "Medium" = "#9ecae1", "High" = "#08306b")

bin_df <- data.frame(
  xmin = bins[-length(bins)],
  xmax = bins[-1],
  ymin = -Inf,
  ymax = Inf,
  bin = bin_labels
)

#-----------------------------
# 6. Plot segmented regression with bins
#-----------------------------
ggplot(fatalities_clean, aes(x = exits, y = cum_per_fatal)) +
  # Data points
  geom_point(size = 2, alpha = 0.6) +
  # Segmented regression line
  geom_line(data = pred_grid, aes(x = exits, y = fit), color = "red", size = 1) +
  # Breakpoint vertical line
  geom_vline(xintercept = bp, linetype = "dashed", color = "black") +
  # Bin colors
  #scale_fill_manual(values = setNames(bin_colors, bin_labels)) +
  # Labels and theme
  labs(
    x = "Number of Exits",
    y = "Cumulative Fatality (%)",
    fill = "Percentile Bin",
    title = paste0("Segmented Regression with Breakpoint at exits = ", round(bp, 2))
  ) +
  theme_classic(base_size = 14)

#-----------------------------
# 7. Check linear regression
#-----------------------------
lm_exits_pop <- lm(exits ~ population, data = fatalities_clean)

# View summary
summary(lm_exits_pop)
