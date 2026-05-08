import styled from "styled-components";

const StyledControls = styled.nav`
  align-items: center;
  background-color: rgb(50 54 57);
  box-shadow: 0 0 5px hsl(0 0% 10% / 50%);
  display: flex;
  flex-wrap: wrap;
  gap: 6px 0;
  min-height: 40px;
  position: absolute;
  top: ${({ theme }) => theme.sizes.titleBar.height}px;
  width: 100%;
  z-index: 1;

  .side-menu {
    display: flex;
    overflow: hidden;
    place-items: center;
    white-space: nowrap;
    width: 100%;

    span {
      margin-right: 20px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    &:first-child {
      color: #fff;
      font-size: 14px;
      margin-left: 16px;
      place-content: flex-start;
    }

    &:last-child {
      margin-right: 16px;
      place-content: flex-end;
    }
  }

  button {
    border-radius: 50%;
    display: flex;
    font-size: 24px;
    height: 30px;
    place-content: center;
    place-items: center;
    width: 30px;

    &.subtract {
      margin-right: 7px;
    }

    &.add {
      margin-left: 7px;
    }

    &:last-child {
      margin-left: 7px;
    }

    &:hover {
      background-color: rgb(66 70 73);
    }

    svg {
      fill: #fff;
      height: 12px;
      stroke: #fff;
      width: 12px;
    }

    &:disabled {
      background-color: initial;

      svg {
        fill: rgb(110 112 114);
        stroke: rgb(110 112 114);
      }
    }

    &.download {
      svg {
        margin-left: 1px;
        scale: 1.15;
        stroke-width: 1.75;
        transform: scale(1.25, 1);
      }
    }
  }

  ol {
    display: flex;
    flex-direction: row;
    height: 100%;
    place-content: center;
    place-items: center;
    width: 100%;

    li {
      color: #fff;
      display: flex;
      flex-direction: row;
      font-size: 14px;

      input {
        background-color: rgb(25 27 28);
        color: #fff;
        height: 20px;
        text-align: center;

        &:disabled {
          color: rgb(110 112 114);
        }
      }

      &:not(:last-child)::after {
        background-color: rgb(112 115 117);
        content: "";
        margin-left: 20px;
        width: 1px;
      }

      &.pages {
        letter-spacing: 1.5px;
        line-height: 20px;
        padding-right: 10px;
        width: max-content;

        input {
          margin: 0 5px;
          width: 24px;
        }
      }

      &.scale {
        display: flex;
        place-items: center;

        input {
          width: 45px;
        }
      }

      &.pdf-icon-tools {
        align-items: center;
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        max-width: none;
        place-items: center;

        button.icon-tool {
          border-radius: 8px;
          color: #fff;
          font-size: 14px;
          font-weight: 600;
          height: 32px;
          min-height: 32px;
          padding: 0;
          width: 32px;

          svg {
            fill: currentColor;
            height: 15px;
            stroke: none;
            width: 15px;
          }

          &.active {
            background-color: rgb(59 130 246 / 35%);
            box-shadow: 0 0 0 1px rgb(147 197 253 / 80%);
          }
        }

        .more-menu-wrap {
          display: inline-flex;
          position: relative;
        }

        .more-dropdown {
          background-color: rgb(40 44 47);
          border-radius: 10px;
          box-shadow: 0 8px 24px hsl(0 0% 0% / 45%);
          display: flex;
          flex-direction: column;
          gap: 4px;
          min-width: 150px;
          padding: 8px;
          position: absolute;
          right: 0;
          top: calc(100% + 6px);
          z-index: 60;
        }

        .more-dd-row {
          align-items: center;
          background-color: rgb(55 59 62);
          border: none;
          border-radius: 6px;
          color: #fff;
          cursor: pointer;
          display: flex;
          font-size: 13px;
          gap: 8px;
          padding: 8px 10px;
          text-align: left;

          &:disabled {
            cursor: default;
            opacity: 0.45;
          }

          &:hover:not(:disabled) {
            background-color: rgb(66 70 73);
          }
        }

        .more-dd-icon {
          display: flex;
          height: 18px;
          place-content: center;
          place-items: center;
          width: 18px;

          svg {
            fill: currentColor;
            height: 16px;
            width: 16px;
          }
        }
      }
    }
  }
`;

export default StyledControls;
